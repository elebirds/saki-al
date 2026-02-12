from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
import saki_api.infra.grpc.dispatcher as dispatcher_module
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.modules.shared.modeling.enums import ALLoopMode, ALLoopStatus, AuthorType, JobStatusV2, JobTaskStatus, JobTaskType, LoopPhase, TaskType
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.domain.loop import ALLoop


@pytest.fixture
async def dispatcher_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_dispatcher_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(dispatcher_module, "SessionLocal", session_local)
    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_EXECUTOR_ALLOWLIST", [])
    monkeypatch.setattr(dispatcher_module.settings, "RUNTIME_ASSIGN_ACK_TIMEOUT_SEC", 1)

    dispatcher = dispatcher_module.RuntimeDispatcher()
    try:
        yield dispatcher, session_local
    finally:
        await engine.dispose()


async def _seed_job_and_task(
    session_local: async_sessionmaker[AsyncSession],
    *,
    plugin_id: str = "demo_det_v1",
    task_status: JobTaskStatus = JobTaskStatus.PENDING,
) -> tuple[Job, JobTask]:
    async with session_local() as session:
        project = Project(name=f"p-{uuid.uuid4().hex[:8]}", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()

        commit = Commit(
            project_id=project.id,
            parent_id=None,
            message="init",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
        )
        session.add(commit)
        await session.flush()

        branch = Branch(
            project_id=project.id,
            name=f"main-{uuid.uuid4().hex[:6]}",
            head_commit_id=commit.id,
            description="main",
            is_protected=True,
        )
        session.add(branch)
        await session.flush()

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            mode=ALLoopMode.ACTIVE_LEARNING,
            phase=LoopPhase.AL_BOOTSTRAP,
            phase_meta={},
            query_strategy="random_baseline",
            model_arch=plugin_id,
            global_config={},
            current_iteration=1,
            status=ALLoopStatus.RUNNING,
            max_rounds=5,
            query_batch_size=10,
            min_seed_labeled=1,
            min_new_labels_per_round=1,
            stop_patience_rounds=2,
            stop_min_gain=0.001,
            auto_register_model=False,
        )
        session.add(loop)
        await session.flush()

        job = Job(
            project_id=project.id,
            loop_id=loop.id,
            round_index=1,
            mode=ALLoopMode.ACTIVE_LEARNING,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            job_type="loop_round",
            plugin_id=plugin_id,
            query_strategy="random_baseline",
            params={"epochs": 1},
            resources={"gpu_count": 0, "cpu_workers": 2, "memory_mb": 1024},
            source_commit_id=commit.id,
            final_metrics={},
            final_artifacts={},
        )
        session.add(job)
        await session.flush()

        task = JobTask(
            job_id=job.id,
            task_type=JobTaskType.TRAIN,
            status=task_status,
            round_index=1,
            task_index=1,
            depends_on=[],
            params={"epochs": 1},
            metrics={},
            artifacts={},
            source_commit_id=commit.id,
            attempt=1,
            max_attempts=3,
        )
        session.add(task)
        await session.commit()
        await session.refresh(job)
        await session.refresh(task)
        return job, task


@pytest.mark.anyio
async def test_assign_task_and_ack_success_updates_task_and_job(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    job, task = await _seed_job_and_task(session_local)

    await dispatcher.register_executor(
        executor_id="executor-1",
        version="0.1.0",
        plugin_payloads=[{"plugin_id": "demo_det_v1", "version": "0.1.0"}],
        resources={"gpu_count": 0, "cpu_workers": 2, "memory_mb": 2048},
    )

    assigned = await dispatcher.assign_task(task.id)
    assert assigned is True

    message = await dispatcher.get_outgoing("executor-1", timeout=0.5)
    assert message is not None
    assert message.WhichOneof("payload") == "assign_task"
    assert message.assign_task.task.task_id == str(task.id)

    await dispatcher.handle_ack(
        pb.Ack(
            request_id="ack-1",
            ack_for=message.assign_task.request_id,
            status=pb.OK,
            type=pb.ACK_TYPE_ASSIGN_TASK,
            reason=pb.ACK_REASON_ACCEPTED,
            detail="accepted",
        )
    )

    async with session_local() as session:
        persisted_task = await session.get(JobTask, task.id)
        persisted_job = await session.get(Job, job.id)
        assert persisted_task is not None
        assert persisted_job is not None
        assert persisted_task.status == JobTaskStatus.RUNNING
        assert persisted_task.assigned_executor_id == "executor-1"
        assert persisted_job.summary_status == JobStatusV2.JOB_RUNNING


@pytest.mark.anyio
async def test_assign_task_ack_rejected_resets_pending(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    _, task = await _seed_job_and_task(session_local)

    await dispatcher.register_executor(
        executor_id="executor-2",
        version="0.1.0",
        plugin_payloads=[{"plugin_id": "demo_det_v1", "version": "0.1.0"}],
        resources={"gpu_count": 0, "cpu_workers": 2, "memory_mb": 2048},
    )

    assert await dispatcher.assign_task(task.id)
    message = await dispatcher.get_outgoing("executor-2", timeout=0.5)
    assert message is not None

    await dispatcher.handle_ack(
        pb.Ack(
            request_id="ack-2",
            ack_for=message.assign_task.request_id,
            status=pb.ERROR,
            type=pb.ACK_TYPE_ASSIGN_TASK,
            reason=pb.ACK_REASON_REJECTED,
            detail="busy",
        )
    )

    async with session_local() as session:
        persisted_task = await session.get(JobTask, task.id)
        assert persisted_task is not None
        assert persisted_task.status == JobTaskStatus.PENDING
        assert "busy" in (persisted_task.last_error or "")


@pytest.mark.anyio
async def test_stop_task_without_executor_marks_cancelled(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    _, task = await _seed_job_and_task(session_local)

    request_id, dispatched = await dispatcher.stop_task(str(task.id), "user stop")
    assert request_id
    assert dispatched is False

    async with session_local() as session:
        persisted_task = await session.get(JobTask, task.id)
        assert persisted_task is not None
        assert persisted_task.status == JobTaskStatus.CANCELLED
        assert persisted_task.last_error == "user stop"


@pytest.mark.anyio
async def test_cleanup_stale_assignments_resets_task(dispatcher_env):
    dispatcher, session_local = dispatcher_env
    _, task = await _seed_job_and_task(session_local)

    await dispatcher.register_executor(
        executor_id="executor-3",
        version="0.1.0",
        plugin_payloads=[{"plugin_id": "demo_det_v1", "version": "0.1.0"}],
        resources={"gpu_count": 0, "cpu_workers": 2, "memory_mb": 2048},
    )

    assert await dispatcher.assign_task(task.id)

    assert len(dispatcher._pending_assign) == 1  # noqa: SLF001
    pending = next(iter(dispatcher._pending_assign.values()))  # noqa: SLF001
    pending.created_at = datetime.now(UTC) - timedelta(seconds=10)

    await dispatcher._cleanup_stale_assignments()  # noqa: SLF001

    async with session_local() as session:
        persisted_task = await session.get(JobTask, task.id)
        assert persisted_task is not None
        assert persisted_task.status == JobTaskStatus.PENDING
        assert "timeout" in (persisted_task.last_error or "")
