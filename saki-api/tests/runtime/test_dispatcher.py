from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure all SQLModel metadata is imported.
import saki_api.grpc.dispatcher as dispatcher_module
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.runtime_executor import RuntimeExecutor


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


async def _create_pending_job(session_local: async_sessionmaker[AsyncSession], *, plugin_id: str = "demo_det_v1") -> Job:
    job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        iteration=1,
        status=TrainingJobStatus.PENDING,
        job_type="train_detection",
        plugin_id=plugin_id,
        mode="active_learning",
        query_strategy="uncertainty_1_minus_max_conf",
        params={},
        resources={"gpu_count": 1, "memory_mb": 0},
        source_commit_id=uuid.uuid4(),
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

    future_retry_ts = int((datetime.utcnow() + timedelta(minutes=30)).timestamp())
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
