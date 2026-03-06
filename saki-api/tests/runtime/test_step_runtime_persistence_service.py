from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
import saki_api.modules.annotation.domain.annotation  # noqa: F401
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.domain.task_metric_point import TaskMetricPoint
from saki_api.modules.runtime.service.application.event_dto import (
    RuntimeTaskEventDTO,
    RuntimeTaskResultDTO,
)
from saki_api.modules.runtime.service.persistence.task_runtime_persistence_service import RuntimeTaskPersistenceService
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    LoopMode,
    LoopPhase,
    RoundStatus,
    StepDispatchKind,
    StepStatus,
    StepType,
    TaskType,
    RuntimeTaskKind,
    RuntimeTaskStatus,
    RuntimeTaskType,
)


@pytest.fixture
async def persistence_env(tmp_path):
    db_path = tmp_path / "step_runtime_persistence.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_train_step(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    project = Project(name="persistence-project", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    init_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
    )
    session.add(init_commit)
    await session.flush()

    branch = Branch(
        project_id=project.id,
        name="master",
        head_commit_id=init_commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.flush()

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="loop-a",
        mode=LoopMode.ACTIVE_LEARNING,
        phase=LoopPhase.AL_BOOTSTRAP,
        model_arch="yolo_det_v1",
        config={},
    )
    session.add(loop)
    await session.flush()

    round_row = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        mode=LoopMode.ACTIVE_LEARNING,
        state=RoundStatus.RUNNING,
        step_counts={},
        plugin_id=loop.model_arch,
        resolved_params={},
        resources={},
        input_commit_id=init_commit.id,
        final_metrics={},
        final_artifacts={},
    )
    session.add(round_row)
    await session.flush()

    step = Step(
        round_id=round_row.id,
        step_type=StepType.TRAIN,
        dispatch_kind=StepDispatchKind.DISPATCHABLE,
        state=StepStatus.RUNNING,
        round_index=1,
        step_index=1,
        depends_on_step_ids=[],
        resolved_params={},
        metrics={},
        artifacts={},
        input_commit_id=init_commit.id,
        attempt=1,
        max_attempts=3,
    )
    await _attach_step_task(
        session=session,
        project_id=project.id,
        step=step,
        plugin_id=loop.model_arch,
    )
    await session.commit()

    return step.id, round_row.id


async def _attach_step_task(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    step: Step,
    plugin_id: str,
) -> Task:
    task = Task(
        project_id=project_id,
        kind=RuntimeTaskKind.STEP,
        task_type=RuntimeTaskType(step.step_type.value),
        status=RuntimeTaskStatus(step.state.value),
        plugin_id=plugin_id,
        input_commit_id=step.input_commit_id,
        resolved_params=dict(step.resolved_params or {}),
        attempt=max(1, int(step.attempt or 1)),
        max_attempts=max(1, int(step.max_attempts or 1)),
    )
    session.add(task)
    await session.flush()
    step.task_id = task.id
    session.add(step)
    await session.flush()
    return task


async def _seed_train_eval_select_steps(session: AsyncSession) -> tuple[dict[str, uuid.UUID], uuid.UUID]:
    train_step_id, round_id = await _seed_train_step(session)
    train_step = await session.get(Step, train_step_id)
    assert train_step is not None

    eval_step = Step(
        round_id=round_id,
        step_type=StepType.EVAL,
        dispatch_kind=StepDispatchKind.DISPATCHABLE,
        state=StepStatus.RUNNING,
        round_index=int(train_step.round_index),
        step_index=2,
        depends_on_step_ids=[],
        resolved_params={},
        metrics={},
        artifacts={},
        input_commit_id=train_step.input_commit_id,
        attempt=1,
        max_attempts=3,
    )
    select_step = Step(
        round_id=round_id,
        step_type=StepType.SELECT,
        dispatch_kind=StepDispatchKind.ORCHESTRATOR,
        state=StepStatus.RUNNING,
        round_index=int(train_step.round_index),
        step_index=3,
        depends_on_step_ids=[],
        resolved_params={},
        metrics={},
        artifacts={},
        input_commit_id=train_step.input_commit_id,
        attempt=1,
        max_attempts=3,
    )
    round_row = await session.get(Round, round_id)
    if round_row is None:
        raise RuntimeError("round not found while attaching step tasks")
    loop_row = await session.get(Loop, round_row.loop_id)
    if loop_row is None:
        raise RuntimeError("loop not found while attaching step tasks")
    project_id = uuid.UUID(str(loop_row.project_id))
    await _attach_step_task(
        session=session,
        project_id=project_id,
        step=train_step,
        plugin_id=loop_row.model_arch,
    )
    await _attach_step_task(
        session=session,
        project_id=project_id,
        step=eval_step,
        plugin_id=loop_row.model_arch,
    )
    await _attach_step_task(
        session=session,
        project_id=project_id,
        step=select_step,
        plugin_id=loop_row.model_arch,
    )
    await session.commit()

    return {
        "train": train_step_id,
        "eval": eval_step.id,
        "select": select_step.id,
    }, round_id


@pytest.mark.anyio
async def test_persist_step_result_no_longer_appends_terminal_metric_points(persistence_env):
    session_local = persistence_env

    async with session_local() as session:
        step_id, _ = await _seed_train_step(session)
        persistence = RuntimeTaskPersistenceService(session)
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        await persistence.persist_task_event(
            RuntimeTaskEventDTO(
                task_id=step.task_id,
                seq=1,
                ts=datetime.now(UTC),
                event_type="metric",
                payload={"step": 3, "epoch": 3, "metrics": {"map50": 0.62, "loss": 0.40}},
            )
        )
        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"map50": 0.66, "loss": 0.35},
                artifacts=[],
                candidates=[],
            )
        )
        await session.commit()
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        metric_rows = list(
            (
                await session.exec(
                    select(TaskMetricPoint)
                    .where(TaskMetricPoint.task_id == step.task_id)
                    .order_by(TaskMetricPoint.metric_step.asc(), TaskMetricPoint.metric_name.asc())
                )
            ).all()
        )
        assert len(metric_rows) == 2
        assert {item.metric_name for item in metric_rows} == {"map50", "loss"}
        assert {int(item.metric_step) for item in metric_rows} == {3}


@pytest.mark.anyio
async def test_persist_step_result_without_metric_events_keeps_series_empty(persistence_env):
    session_local = persistence_env

    async with session_local() as session:
        step_id, round_id = await _seed_train_step(session)
        persistence = RuntimeTaskPersistenceService(session)
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"map50": 0.70, "loss": 0.30},
                artifacts=[],
                candidates=[],
            )
        )
        await session.commit()
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        metric_rows = list(
            (await session.exec(select(TaskMetricPoint).where(TaskMetricPoint.task_id == step.task_id))).all()
        )
        assert metric_rows == []

        assert float(step.metrics.get("map50", 0.0)) == pytest.approx(0.70)
        assert float(step.metrics.get("loss", 0.0)) == pytest.approx(0.30)

        round_row = await session.get(Round, round_id)
        assert round_row is not None
        assert float(round_row.final_metrics.get("map50", 0.0)) == pytest.approx(0.70)
        assert float(round_row.final_metrics.get("loss", 0.0)) == pytest.approx(0.30)


@pytest.mark.anyio
async def test_persist_multi_step_result_keeps_eval_metrics_as_round_final(persistence_env):
    session_local = persistence_env

    async with session_local() as session:
        step_ids, round_id = await _seed_train_eval_select_steps(session)
        persistence = RuntimeTaskPersistenceService(session)
        train_step = await session.get(Step, step_ids["train"])
        eval_step = await session.get(Step, step_ids["eval"])
        select_step = await session.get(Step, step_ids["select"])
        assert train_step is not None and train_step.task_id is not None
        assert eval_step is not None and eval_step.task_id is not None
        assert select_step is not None and select_step.task_id is not None

        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=train_step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"loss": 0.55},
                artifacts=[],
                candidates=[],
            )
        )
        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=eval_step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"map50": 0.81, "precision": 0.89},
                artifacts=[],
                candidates=[],
            )
        )
        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=select_step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={},
                artifacts=[],
                candidates=[],
            )
        )
        await session.commit()

        round_row = await session.get(Round, round_id)
        assert round_row is not None
        assert round_row.state == RoundStatus.COMPLETED
        assert round_row.final_metrics == {"map50": 0.81, "precision": 0.89}


@pytest.mark.anyio
async def test_persist_task_result_projects_back_to_step_without_step_id_input(persistence_env):
    session_local = persistence_env

    async with session_local() as session:
        step_id, round_id = await _seed_train_step(session)
        persistence = RuntimeTaskPersistenceService(session)
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        await persistence.persist_task_event(
            RuntimeTaskEventDTO(
                task_id=step.task_id,
                seq=1,
                ts=datetime.now(UTC),
                event_type="status",
                payload={"reason": "bootstrap"},
                status=StepStatus.RUNNING,
            )
        )
        await session.flush()

        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"map50": 0.77, "loss": 0.28},
                artifacts=[],
                candidates=[],
            )
        )
        await session.commit()

        refreshed_step = await session.get(Step, step_id)
        assert refreshed_step is not None
        assert refreshed_step.state == StepStatus.SUCCEEDED
        assert float(refreshed_step.metrics.get("map50", 0.0)) == pytest.approx(0.77)
        assert float(refreshed_step.metrics.get("loss", 0.0)) == pytest.approx(0.28)

        round_row = await session.get(Round, round_id)
        assert round_row is not None
        assert float(round_row.final_metrics.get("map50", 0.0)) == pytest.approx(0.77)
        assert float(round_row.final_metrics.get("loss", 0.0)) == pytest.approx(0.28)


@pytest.mark.anyio
async def test_recompute_round_summary_uses_task_result_artifacts_as_source_of_truth(persistence_env):
    session_local = persistence_env

    async with session_local() as session:
        step_id, round_id = await _seed_train_step(session)
        persistence = RuntimeTaskPersistenceService(session)
        step = await session.get(Step, step_id)
        assert step is not None
        assert step.task_id is not None

        await persistence.persist_task_result(
            RuntimeTaskResultDTO(
                task_id=step.task_id,
                status=StepStatus.SUCCEEDED,
                metrics={"map50": 0.81},
                artifacts=[
                    {
                        "name": "best.pt",
                        "kind": "weights",
                        "uri": "https://example.com/task-best.pt",
                        "meta": {"size": 1024},
                    }
                ],
                candidates=[],
            )
        )
        await session.flush()

        # Tamper step projection; round summary should still follow task._result_artifacts.
        step = await session.get(Step, step_id)
        assert step is not None
        step.artifacts = {
            "tampered.pt": {
                "kind": "weights",
                "uri": "https://example.com/step-tampered.pt",
                "meta": {},
            }
        }
        session.add(step)
        await session.flush()

        await persistence._recompute_round_summary(round_id)
        await session.commit()

        round_row = await session.get(Round, round_id)
        assert round_row is not None
        assert "best.pt" in (round_row.final_artifacts or {})
        assert "tampered.pt" not in (round_row.final_artifacts or {})
