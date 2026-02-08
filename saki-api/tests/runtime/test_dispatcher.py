from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure all SQLModel metadata is imported.
import saki_api.grpc.dispatcher as dispatcher_module
from saki_api.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.models.l3.runtime_executor_stats import RuntimeExecutorStats


@pytest.fixture
async def dispatcher_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_dispatcher.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(dispatcher_module, "SessionLocal", session_local)
    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_EXECUTOR_ALLOWLIST", [])

    dispatcher = dispatcher_module.RuntimeDispatcher()
    dispatcher._schedule_dispatch = lambda: None  # type: ignore[assignment]
    try:
        yield dispatcher, session_local
    finally:
        await engine.dispose()


async def _create_pending_job(
        session_local: async_sessionmaker[AsyncSession],
        *,
        plugin_id: str = "demo_det_v1",
        resources: dict | None = None,
        params: dict | None = None,
) -> Job:
    job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        iteration=1,
        status=TrainingJobStatus.PENDING,
        job_type="train_detection",
        plugin_id=plugin_id,
        mode="active_learning",
        query_strategy="uncertainty_1_minus_max_conf",
        params=dict(params or {}),
        resources=resources if isinstance(resources, dict) else {"gpu_count": 1, "memory_mb": 0},
        source_commit_id=uuid.uuid4(),
    )
    async with session_local() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


async def _create_job(
        session_local: async_sessionmaker[AsyncSession],
        *,
        status: TrainingJobStatus = TrainingJobStatus.PENDING,
        plugin_id: str = "demo_det_v1",
        iteration: int = 1,
        assigned_executor_id: str | None = None,
) -> Job:
    job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        iteration=iteration,
        status=status,
        job_type="train_detection",
        plugin_id=plugin_id,
        mode="active_learning",
        query_strategy="uncertainty_1_minus_max_conf",
        params={},
        resources={"gpu_count": 1, "memory_mb": 0},
        source_commit_id=uuid.uuid4(),
        assigned_executor_id=assigned_executor_id,
    )
    async with session_local() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


@pytest.mark.anyio
async def test_assign_and_ack_success_updates_job_and_executor(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None

    message = await asyncio.wait_for(queue.get(), timeout=1)
    assert message.WhichOneof("payload") == "assign_job"
    assert message.assign_job.job.job_id == str(job.id)
    assert message.assign_job.job.plugin_id == "demo_det_v1"
    assert message.assign_job.job.iteration == 1

    await dispatcher.handle_ack(ack_for=assigned.request_id, status=pb.OK, message="accepted")

    async with session_local() as session:
        persisted_job = await session.get(Job, job.id)
        assert persisted_job is not None
        assert persisted_job.status == TrainingJobStatus.RUNNING
        assert persisted_job.started_at is not None
        assert persisted_job.assigned_executor_id == "executor-1"

        executor = (
            await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == "executor-1"))
        ).first()
        assert executor is not None
        assert executor.status == "busy"
        assert executor.current_job_id == str(job.id)


@pytest.mark.anyio
async def test_assign_respects_resource_capabilities_and_labels(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(
        session_local,
        resources={
            "gpu_count": 1,
            "memory_mb": 0,
            "capabilities": ["obb", "cuda"],
            "labels": {"zone": "cn-north"},
        },
    )

    await dispatcher.register(
        executor_id="executor-cap-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={
            "gpu_count": 1,
            "memory_mb": 32000,
            "capabilities": ["cuda"],
            "labels": {"zone": "cn-north"},
        },
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is None

    await dispatcher.heartbeat(
        executor_id="executor-cap-1",
        busy=False,
        current_job_id=None,
        resources={
            "gpu_count": 1,
            "memory_mb": 32000,
            "capabilities": ["obb", "cuda"],
            "labels": {"zone": "cn-north"},
        },
    )
    assigned_after_update = await dispatcher.assign_job(job)
    assert assigned_after_update is not None


@pytest.mark.anyio
async def test_assign_auto_prefers_cuda_backend_and_persists_resolved_device(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue_cpu: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    queue_cuda: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(
        session_local,
        resources={"gpu_count": 0, "memory_mb": 0},
        params={"device": "auto"},
    )

    await dispatcher.register(
        executor_id="executor-auto-cpu",
        queue=queue_cpu,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={
            "gpu_count": 0,
            "memory_mb": 32000,
            "accelerators": [
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )
    await dispatcher.register(
        executor_id="executor-auto-cuda",
        queue=queue_cuda,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={
            "gpu_count": 1,
            "memory_mb": 32000,
            "accelerators": [
                {"type": "cuda", "available": True, "device_count": 1, "device_ids": ["0"]},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )

    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    assert assigned.executor_id == "executor-auto-cuda"
    assert queue_cpu.empty()

    message = await asyncio.wait_for(queue_cuda.get(), timeout=1)
    assert message.WhichOneof("payload") == "assign_job"
    params = runtime_codec.struct_to_dict(message.assign_job.job.params)
    assert params.get("_resolved_device_backend") == "cuda"

    async with session_local() as session:
        persisted_job = await session.get(Job, job.id)
        assert persisted_job is not None
        assert (persisted_job.params or {}).get("_resolved_device_backend") == "cuda"


@pytest.mark.anyio
async def test_assign_explicit_cuda_rejects_cpu_only_executor(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue_cpu: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    queue_cuda: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(
        session_local,
        resources={"gpu_count": 0, "memory_mb": 0},
        params={"device": "0"},
    )

    await dispatcher.register(
        executor_id="executor-explicit-cpu",
        queue=queue_cpu,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={
            "gpu_count": 0,
            "memory_mb": 32000,
            "accelerators": [
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )
    assert await dispatcher.assign_job(job) is None

    await dispatcher.register(
        executor_id="executor-explicit-cuda",
        queue=queue_cuda,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={
            "gpu_count": 1,
            "memory_mb": 32000,
            "accelerators": [
                {"type": "cuda", "available": True, "device_count": 1, "device_ids": ["0"]},
            ],
        },
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    assert assigned.executor_id == "executor-explicit-cuda"

@pytest.mark.anyio
async def test_assign_and_ack_failure_releases_executor(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-2",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    _ = await asyncio.wait_for(queue.get(), timeout=1)

    await dispatcher.handle_ack(ack_for=assigned.request_id, status=pb.ERROR, message="reject assignment")

    async with session_local() as session:
        persisted_job = await session.get(Job, job.id)
        assert persisted_job is not None
        assert persisted_job.status == TrainingJobStatus.FAILED
        assert persisted_job.last_error == "reject assignment"
        assert persisted_job.ended_at is not None
        assert persisted_job.assigned_executor_id is None

        executor = (
            await session.exec(select(RuntimeExecutor).where(RuntimeExecutor.executor_id == "executor-2"))
        ).first()
        assert executor is not None
        assert executor.status == "idle"
        assert executor.current_job_id is None


@pytest.mark.anyio
async def test_stop_job_dispatches_command_and_clears_pending_stop_on_ack(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-3",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    _ = await asyncio.wait_for(queue.get(), timeout=1)
    await dispatcher.handle_ack(ack_for=assigned.request_id, status=pb.OK, message="accepted")

    request_id, dispatched = await dispatcher.stop_job(str(job.id), reason="user_cancel")
    assert dispatched is True

    stop_message = await asyncio.wait_for(queue.get(), timeout=1)
    assert stop_message.WhichOneof("payload") == "stop_job"
    assert stop_message.stop_job.job_id == str(job.id)
    assert stop_message.stop_job.reason == "user_cancel"

    await dispatcher.handle_ack(ack_for=request_id, status=pb.OK, message="stopping")
    assert request_id not in dispatcher._pending_stop

    _, dispatched_missing = await dispatcher.stop_job("missing-job-id", reason="none")
    assert dispatched_missing is False


@pytest.mark.anyio
async def test_stop_job_duplicate_request_is_deduplicated(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-dup-stop",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    _ = await asyncio.wait_for(queue.get(), timeout=1)
    await dispatcher.handle_ack(ack_for=assigned.request_id, status=pb.OK, message="accepted")

    first_request_id, first_dispatched = await dispatcher.stop_job(str(job.id), reason="user_cancel")
    second_request_id, second_dispatched = await dispatcher.stop_job(str(job.id), reason="user_cancel")

    assert first_dispatched is True
    assert second_dispatched is True
    assert second_request_id == first_request_id

    stop_message = await asyncio.wait_for(queue.get(), timeout=1)
    assert stop_message.WhichOneof("payload") == "stop_job"
    assert stop_message.stop_job.request_id == first_request_id
    assert queue.empty()


@pytest.mark.anyio
async def test_dispatch_pending_jobs_skips_retry_not_ready(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()

    future_retry_ts = int((datetime.now(UTC) + timedelta(minutes=30)).timestamp())
    normal_job = await _create_pending_job(session_local)
    delayed_job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        iteration=2,
        status=TrainingJobStatus.PENDING,
        job_type="train_detection",
        plugin_id="demo_det_v1",
        mode="active_learning",
        query_strategy="uncertainty_1_minus_max_conf",
        params={"_retry_not_before_ts": future_retry_ts},
        resources={"gpu_count": 1, "memory_mb": 0},
        source_commit_id=uuid.uuid4(),
    )
    async with session_local() as session:
        session.add(delayed_job)
        await session.commit()
        await session.refresh(delayed_job)

    await dispatcher.register(
        executor_id="executor-4",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )

    await dispatcher.dispatch_pending_jobs()
    first = await asyncio.wait_for(queue.get(), timeout=1)
    assert first.WhichOneof("payload") == "assign_job"
    assert first.assign_job.job.job_id == str(normal_job.id)

    assert queue.empty()

    async with session_local() as session:
        persisted_normal = await session.get(Job, normal_job.id)
        persisted_delayed = await session.get(Job, delayed_job.id)
        assert persisted_normal is not None
        assert persisted_delayed is not None
        assert persisted_normal.assigned_executor_id == "executor-4"
        assert persisted_delayed.assigned_executor_id is None


@pytest.mark.anyio
async def test_assign_ack_timeout_releases_executor_and_redispatches(dispatcher_env, monkeypatch):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_ASSIGN_ACK_TIMEOUT_SEC", 1)

    await dispatcher.register(
        executor_id="executor-timeout-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    first = await asyncio.wait_for(queue.get(), timeout=1)
    assert first.WhichOneof("payload") == "assign_job"

    pending = dispatcher._pending_assign.get(assigned.request_id)  # noqa: SLF001
    assert pending is not None
    pending.created_at = pending.created_at - timedelta(seconds=5)

    await dispatcher.reap_assign_timeouts()
    assert assigned.request_id not in dispatcher._pending_assign  # noqa: SLF001

    async with session_local() as session:
        persisted_job = await session.get(Job, job.id)
        assert persisted_job is not None
        assert persisted_job.status == TrainingJobStatus.PENDING
        assert persisted_job.assigned_executor_id is None
        assert "assign_ack_timeout" in (persisted_job.last_error or "")

        executor = (
            await session.exec(
                select(RuntimeExecutor).where(RuntimeExecutor.executor_id == "executor-timeout-1")
            )
        ).first()
        assert executor is not None
        assert executor.status == "idle"
        assert executor.current_job_id is None

    await dispatcher.dispatch_pending_jobs()
    second = await asyncio.wait_for(queue.get(), timeout=1)
    assert second.WhichOneof("payload") == "assign_job"
    assert second.assign_job.job.job_id == str(job.id)


@pytest.mark.anyio
async def test_unregister_clears_pending_assign_records(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-unregister-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None
    first = await asyncio.wait_for(queue.get(), timeout=1)
    assert first.WhichOneof("payload") == "assign_job"
    assert assigned.request_id in dispatcher._pending_assign  # noqa: SLF001

    await dispatcher.unregister("executor-unregister-1")
    assert assigned.request_id not in dispatcher._pending_assign  # noqa: SLF001


@pytest.mark.anyio
async def test_metrics_snapshot_and_executor_pending_snapshot(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
    job = await _create_pending_job(session_local)

    await dispatcher.register(
        executor_id="executor-metric-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    assigned = await dispatcher.assign_job(job)
    assert assigned is not None

    snapshot = await dispatcher.metrics_snapshot()
    assert snapshot["session_online_count"] == 1
    assert snapshot["pending_assign_count"] == 1
    assert snapshot["pending_stop_count"] == 0
    assert snapshot["latest_session_heartbeat_at"] is not None

    pending = await dispatcher.executor_pending_snapshot(
        executor_id="executor-metric-1",
        current_job_id=str(job.id),
    )
    assert pending["pending_assign_count"] == 1
    assert pending["pending_stop_count"] == 0


@pytest.mark.anyio
async def test_recover_after_api_restart_clears_stale_assignments_and_running_jobs(dispatcher_env):
    dispatcher, session_local = dispatcher_env

    pending_job = await _create_job(
        session_local,
        status=TrainingJobStatus.PENDING,
        assigned_executor_id="executor-recover-1",
        iteration=2,
    )
    running_job = await _create_job(
        session_local,
        status=TrainingJobStatus.RUNNING,
        assigned_executor_id="executor-recover-2",
        iteration=3,
    )

    async with session_local() as session:
        session.add(
            RuntimeExecutor(
                executor_id="executor-recover-1",
                version="0.1.0",
                status="busy",
                is_online=True,
                current_job_id=str(pending_job.id),
            )
        )
        session.add(
            RuntimeExecutor(
                executor_id="executor-recover-2",
                version="0.1.0",
                status="busy",
                is_online=True,
                current_job_id=str(running_job.id),
            )
        )
        await session.commit()

    summary = await dispatcher.recover_after_api_restart()
    assert summary["reset_executors"] == 2
    assert summary["recovered_pending_assignments"] == 1
    assert summary["failed_running_jobs"] == 1
    assert summary["created_retry_jobs"] == 1

    async with session_local() as session:
        persisted_pending = await session.get(Job, pending_job.id)
        assert persisted_pending is not None
        assert persisted_pending.status == TrainingJobStatus.PENDING
        assert persisted_pending.assigned_executor_id is None
        assert "api_restart_recover" in (persisted_pending.last_error or "")

        persisted_running = await session.get(Job, running_job.id)
        assert persisted_running is not None
        assert persisted_running.status == TrainingJobStatus.FAILED
        assert persisted_running.assigned_executor_id is None
        assert persisted_running.ended_at is not None
        assert "api restarted during running job" in (persisted_running.last_error or "")

        retry_rows = await session.exec(
            select(Job).where(
                Job.loop_id == running_job.loop_id,
                Job.status == TrainingJobStatus.PENDING,
                Job.retry_count == running_job.retry_count + 1,
            )
        )
        retry_jobs = list(retry_rows.all())
        assert len(retry_jobs) == 1
        assert retry_jobs[0].assigned_executor_id is None

        executor_rows = await session.exec(select(RuntimeExecutor).order_by(RuntimeExecutor.executor_id.asc()))
        executors = list(executor_rows.all())
        assert len(executors) == 2
        for executor in executors:
            assert executor.is_online is False
            assert executor.status == "offline"
            assert executor.current_job_id is None


@pytest.mark.anyio
async def test_runtime_stats_snapshot_persist_and_cleanup(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    queue: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()

    dispatcher._stats_persist_interval = timedelta(seconds=0)
    dispatcher._stats_cleanup_interval = timedelta(seconds=0)

    async with session_local() as session:
        session.add(
            RuntimeExecutorStats(
                ts=datetime.now(UTC) - timedelta(days=8),
                total_count=0,
                online_count=0,
                busy_count=0,
                available_count=0,
                availability_rate=0.0,
                pending_assign_count=0,
                pending_stop_count=0,
            )
        )
        await session.commit()

    await dispatcher.register(
        executor_id="executor-stats-1",
        queue=queue,
        version="0.1.0",
        plugin_ids={"demo_det_v1"},
        resources={"gpu_count": 1, "memory_mb": 32000},
    )
    await dispatcher.heartbeat(
        executor_id="executor-stats-1",
        busy=True,
        current_job_id=None,
        resources={"gpu_count": 1, "memory_mb": 32000},
    )

    async with session_local() as session:
        rows = await session.exec(select(RuntimeExecutorStats).order_by(RuntimeExecutorStats.ts.asc()))
        snapshots = list(rows.all())
        assert snapshots
        cutoff = datetime.now(UTC) - timedelta(days=7)
        assert all(
            (item.ts if item.ts.tzinfo else item.ts.replace(tzinfo=UTC)) >= cutoff
            for item in snapshots
        )
        latest = snapshots[-1]
        assert latest.total_count == 1
        assert latest.online_count == 1
        assert latest.busy_count == 1


@pytest.mark.anyio
async def test_recover_after_api_restart_skips_when_tables_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_dispatcher_empty.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(dispatcher_module, "SessionLocal", session_local)
    dispatcher = dispatcher_module.RuntimeDispatcher()

    try:
        summary = await dispatcher.recover_after_api_restart()
        assert summary == {
            "reset_executors": 0,
            "recovered_pending_assignments": 0,
            "failed_running_jobs": 0,
            "created_retry_jobs": 0,
        }
    finally:
        await engine.dispose()
