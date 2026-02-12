from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
import saki_api.infra.grpc.runtime_control as runtime_control_module
from saki_api.infra.grpc.runtime_control import RuntimeControlService
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.modules.shared.modeling.enums import ALLoopMode, ALLoopStatus, AuthorType, JobStatusV2, JobTaskStatus, JobTaskType, LoopPhase, TaskType
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.domain.job_task import JobTask
from saki_api.modules.runtime.domain.loop import ALLoop
from saki_api.modules.runtime.domain.task_event import TaskEvent


@pytest.fixture
async def stream_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_stream_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(runtime_control_module, "SessionLocal", session_local)
    service = RuntimeControlService()

    register_calls = []
    heartbeat_calls = []
    ack_calls = []
    unregister_calls = []

    async def fake_register_executor(*, executor_id, version, plugin_payloads, resources):
        register_calls.append((executor_id, version, plugin_payloads, resources))

    async def fake_handle_heartbeat(*, executor_id, busy, current_task_id, resources):
        heartbeat_calls.append((executor_id, busy, current_task_id, resources))

    async def fake_handle_ack(_ack):
        ack_calls.append(_ack)

    async def fake_get_outgoing(_executor_id, timeout=0.2):  # noqa: ARG001
        return None

    async def fake_unregister(executor_id):
        unregister_calls.append(executor_id)

    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "register_executor", fake_register_executor)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "handle_heartbeat", fake_handle_heartbeat)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "handle_ack", fake_handle_ack)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "get_outgoing", fake_get_outgoing)
    monkeypatch.setattr(runtime_control_module.runtime_dispatcher, "unregister_executor", fake_unregister)

    async with session_local() as session:
        project = Project(name="p", task_type=TaskType.DETECTION, config={})
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

        branch = Branch(project_id=project.id, name="main", head_commit_id=commit.id, description="main", is_protected=True)
        session.add(branch)
        await session.flush()

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            mode=ALLoopMode.ACTIVE_LEARNING,
            phase=LoopPhase.AL_TRAIN,
            phase_meta={},
            query_strategy="random_baseline",
            model_arch="demo_det_v1",
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
            plugin_id="demo_det_v1",
            query_strategy="random_baseline",
            params={},
            resources={},
            source_commit_id=commit.id,
            final_metrics={},
            final_artifacts={},
        )
        session.add(job)
        await session.flush()

        task = JobTask(
            job_id=job.id,
            task_type=JobTaskType.TRAIN,
            status=JobTaskStatus.PENDING,
            round_index=1,
            task_index=1,
            depends_on=[],
            params={},
            metrics={},
            artifacts={},
            source_commit_id=commit.id,
            attempt=1,
            max_attempts=3,
        )
        session.add(task)
        await session.commit()

    try:
        yield service, session_local, task.id, register_calls, heartbeat_calls, ack_calls, unregister_calls
    finally:
        await engine.dispose()


async def _iter_messages(messages: list[pb.RuntimeMessage]) -> AsyncIterator[pb.RuntimeMessage]:
    for item in messages:
        yield item


@pytest.mark.anyio
async def test_runtime_stream_handles_register_heartbeat_event_result(stream_env):
    service, session_local, task_id, register_calls, heartbeat_calls, ack_calls, unregister_calls = stream_env

    messages = [
        pb.RuntimeMessage(
            register=pb.Register(
                request_id="reg-1",
                executor_id="executor-1",
                version="0.1.0",
                plugins=[pb.PluginCapability(plugin_id="demo_det_v1", version="0.1.0")],
            )
        ),
        pb.RuntimeMessage(
            heartbeat=pb.Heartbeat(
                request_id="hb-1",
                executor_id="executor-1",
                busy=True,
                current_task_id=str(task_id),
            )
        ),
        pb.RuntimeMessage(
            task_event=pb.TaskEvent(
                request_id="evt-1",
                task_id=str(task_id),
                seq=1,
                ts=1000,
                status_event=pb.StatusEvent(status=pb.RUNNING, reason="running"),
            )
        ),
        pb.RuntimeMessage(
            task_result=pb.TaskResult(
                request_id="result-1",
                task_id=str(task_id),
                status=pb.SUCCEEDED,
                metrics={"map50": 0.5},
                artifacts=[],
                candidates=[],
            )
        ),
        pb.RuntimeMessage(
            ack=pb.Ack(
                request_id="ack-1",
                ack_for="assign-1",
                status=pb.OK,
                type=pb.ACK_TYPE_ASSIGN_TASK,
                reason=pb.ACK_REASON_ACCEPTED,
            )
        ),
    ]

    responses = []
    async for response in service.Stream(_iter_messages(messages), context=None):
        responses.append(response)

    payload_types = [item.WhichOneof("payload") for item in responses]
    assert payload_types == ["ack", "ack", "ack", "ack"]
    assert register_calls and register_calls[0][0] == "executor-1"
    assert heartbeat_calls and heartbeat_calls[0][2] == str(task_id)
    assert len(ack_calls) == 1
    assert unregister_calls == ["executor-1"]

    async with session_local() as session:
        task = await session.get(JobTask, task_id)
        events = list((await session.exec(select(TaskEvent).where(TaskEvent.task_id == task_id))).all())
        assert task is not None
        assert task.status == JobTaskStatus.SUCCEEDED
        assert len(events) == 1
        assert events[0].event_type == "status"


@pytest.mark.anyio
async def test_handle_unknown_payload_returns_error(stream_env):
    service, _session_local, _task_id, _reg, _hb, _ack, _unreg = stream_env
    response = await service._handle_message(  # noqa: SLF001
        message=pb.RuntimeMessage(),
        state=runtime_control_module._RuntimeStreamState(outbox=runtime_control_module.asyncio.Queue()),
    )
    assert response is not None
    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "unknown_payload"
