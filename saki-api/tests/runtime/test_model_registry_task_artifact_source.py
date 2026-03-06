from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.service.modeling.model_registry_service import ModelService
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    LoopLifecycle,
    LoopMode,
    LoopPhase,
    RoundStatus,
    RuntimeTaskKind,
    RuntimeTaskStatus,
    RuntimeTaskType,
    StepDispatchKind,
    StepStatus,
    StepType,
    TaskType,
)


@pytest.fixture
async def model_registry_env(tmp_path):
    db_path = tmp_path / "model_registry_task_artifact.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_round_with_step_and_task(session: AsyncSession):
    project = Project(name="model-task-source", task_type=TaskType.DETECTION, config={})
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
        name="master",
        head_commit_id=commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.flush()

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="loop-model-source",
        mode=LoopMode.ACTIVE_LEARNING,
        phase=LoopPhase.AL_TRAIN,
        lifecycle=LoopLifecycle.RUNNING,
        model_arch="yolo_det_v1",
        config={},
        max_rounds=5,
        query_batch_size=200,
        min_new_labels_per_round=50,
    )
    session.add(loop)
    await session.flush()

    round_row = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        attempt_index=1,
        mode=LoopMode.ACTIVE_LEARNING,
        state=RoundStatus.COMPLETED,
        step_counts={"succeeded": 1},
        plugin_id=loop.model_arch,
        resolved_params={},
        resources={},
        input_commit_id=commit.id,
        final_metrics={"map50": 0.8},
        final_artifacts={},
    )
    session.add(round_row)
    await session.flush()

    step = Step(
        round_id=round_row.id,
        step_type=StepType.TRAIN,
        dispatch_kind=StepDispatchKind.DISPATCHABLE,
        state=StepStatus.SUCCEEDED,
        round_index=1,
        step_index=1,
        depends_on_step_ids=[],
        resolved_params={},
        metrics={},
        artifacts={
            "step-only.pt": {
                "kind": "weights",
                "uri": "https://example.com/step-only.pt",
                "meta": {},
            }
        },
        input_commit_id=commit.id,
        attempt=1,
        max_attempts=3,
    )
    session.add(step)
    await session.flush()

    task = Task(
        project_id=project.id,
        kind=RuntimeTaskKind.STEP,
        task_type=RuntimeTaskType.TRAIN,
        status=RuntimeTaskStatus.SUCCEEDED,
        plugin_id=loop.model_arch,
        depends_on_task_ids=[],
        input_commit_id=commit.id,
        resolved_params={},
        attempt=1,
        max_attempts=3,
    )
    session.add(task)
    await session.flush()

    step.task_id = task.id
    session.add(step)
    await session.commit()
    return round_row.id, step.id, task.id


@pytest.mark.anyio
async def test_collect_round_artifacts_only_uses_task_result_artifacts(model_registry_env):
    session_local = model_registry_env

    async with session_local() as session:
        round_id, step_id, task_id = await _seed_round_with_step_and_task(session)
        service = ModelService(session)

        # Step.artifacts should no longer be used as fallback source.
        empty_result = await service._collect_round_artifacts(round_id)
        assert empty_result == {}

        task = await service.task_repo.get_by_id_or_raise(task_id)
        task.resolved_params = {
            "_result_artifacts": {
                "best.pt": {
                    "kind": "weights",
                    "uri": "https://example.com/task-best.pt",
                    "meta": {"size": 4096},
                }
            }
        }
        session.add(task)
        await session.commit()

        collected = await service._collect_round_artifacts(round_id)
        assert "best.pt" in collected
        candidate = collected["best.pt"]
        assert candidate.step_id == step_id
        assert candidate.task_id == task_id

        payload = service._build_artifact_payload(candidate)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        assert str(meta.get("task_id")) == str(task_id)
        assert str(meta.get("step_id")) == str(step_id)
