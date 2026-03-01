from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.runtime.service.runtime_service import RuntimeService
from saki_api.modules.shared.modeling.enums import AuthorType, StepStatus, StepType, TaskType
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@dataclass
class _PredictionSetSeedContext:
    actor: User
    project: Project
    branch: Branch
    loop: Loop
    round_row: Round
    score_step: Step
    sample: Sample
    labels_sorted: list[Label]


@pytest.fixture
async def prediction_set_env(tmp_path):
    db_path = tmp_path / "prediction_set_pipeline.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_prediction_context(session: AsyncSession) -> _PredictionSetSeedContext:
    actor = User(email=f"actor-{uuid.uuid4()}@example.com", hashed_password="hashed")
    session.add(actor)
    await session.flush()

    dataset = Dataset(name=f"dataset-{uuid.uuid4()}", owner_id=actor.id)
    session.add(dataset)
    await session.flush()

    sample = Sample(dataset_id=dataset.id, name="sample-a", asset_group={})
    session.add(sample)
    await session.flush()

    project = Project(name=f"project-{uuid.uuid4()}", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

    init_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
        commit_hash=f"init-{uuid.uuid4()}",
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

    label_a = Label(project_id=project.id, name="car", color="#ff0000")
    label_b = Label(project_id=project.id, name="bus", color="#00ff00")
    session.add(label_a)
    session.add(label_b)
    await session.flush()

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="loop-prediction-set",
        model_arch="demo_det_v1",
    )
    session.add(loop)
    await session.flush()

    round_row = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        input_commit_id=init_commit.id,
    )
    session.add(round_row)
    await session.flush()

    score_step = Step(
        round_id=round_row.id,
        step_type=StepType.SCORE,
        round_index=1,
        step_index=1,
        state=StepStatus.SUCCEEDED,
    )
    session.add(score_step)
    await session.flush()

    labels_sorted = list(
        (
            await session.exec(
                select(Label).where(Label.project_id == project.id).order_by(Label.id.asc())
            )
        ).all()
    )
    await session.commit()

    return _PredictionSetSeedContext(
        actor=actor,
        project=project,
        branch=branch,
        loop=loop,
        round_row=round_row,
        score_step=score_step,
        sample=sample,
        labels_sorted=labels_sorted,
    )


@pytest.mark.anyio
async def test_generate_prediction_set_from_reason_snapshot_with_cls_mapping(prediction_set_env):
    session_local = prediction_set_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        session.add(
            StepCandidateItem(
                step_id=ctx.score_step.id,
                sample_id=ctx.sample.id,
                rank=1,
                score=0.77,
                reason={
                    "strategy": "uncertainty",
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "cls_id": 0,
                                "conf": 0.91,
                                "xyxy": [10, 20, 110, 120],
                            }
                        ]
                    },
                },
                prediction_snapshot={},
            )
        )
        await session.commit()

        service = RuntimeService(session)
        prediction_set = await service.generate_prediction_set(
            loop_id=ctx.loop.id,
            payload={"source_step_id": str(ctx.score_step.id)},
            actor_user_id=ctx.actor.id,
        )
        _, items = await service.get_prediction_set_detail(
            prediction_set_id=prediction_set.id,
            item_limit=10,
        )
        assert len(items) == 1
        item = items[0]
        assert item.sample_id == ctx.sample.id
        assert item.label_id == ctx.labels_sorted[0].id
        assert item.confidence == pytest.approx(0.91)
        rect = (item.geometry or {}).get("rect") or {}
        assert rect.get("x") == pytest.approx(10.0)
        assert rect.get("y") == pytest.approx(20.0)
        assert rect.get("width") == pytest.approx(100.0)
        assert rect.get("height") == pytest.approx(100.0)


@pytest.mark.anyio
async def test_apply_prediction_set_writes_model_annotations_with_type_and_ids(prediction_set_env):
    session_local = prediction_set_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        session.add(
            StepCandidateItem(
                step_id=ctx.score_step.id,
                sample_id=ctx.sample.id,
                rank=1,
                score=0.8,
                reason={
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "cls_id": 1,
                                "conf": 0.88,
                                "xyxy": [5, 6, 15, 26],
                            }
                        ]
                    }
                },
                prediction_snapshot={},
            )
        )
        await session.commit()

        service = RuntimeService(session)
        prediction_set = await service.generate_prediction_set(
            loop_id=ctx.loop.id,
            payload={"source_step_id": str(ctx.score_step.id)},
            actor_user_id=ctx.actor.id,
        )
        result = await service.apply_prediction_set(
            prediction_set_id=prediction_set.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )
        assert result["applied_count"] == 1

        draft = await session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == ctx.project.id,
                AnnotationDraft.sample_id == ctx.sample.id,
                AnnotationDraft.user_id == ctx.actor.id,
                AnnotationDraft.branch_name == "master",
            )
        )
        row = draft.one_or_none()
        assert row is not None
        payload = row.payload if isinstance(row.payload, dict) else {}
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        assert len(annotations) == 1
        ann = annotations[0]
        assert ann.get("source") == "model"
        assert ann.get("type") == "rect"
        assert isinstance(ann.get("group_id"), str) and ann.get("group_id")
        assert isinstance(ann.get("lineage_id"), str) and ann.get("lineage_id")


@pytest.mark.anyio
async def test_apply_prediction_set_skips_unresolvable_label(prediction_set_env):
    session_local = prediction_set_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        session.add(
            StepCandidateItem(
                step_id=ctx.score_step.id,
                sample_id=ctx.sample.id,
                rank=1,
                score=0.5,
                reason={
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "conf": 0.5,
                                "xyxy": [1, 2, 3, 4],
                            }
                        ]
                    }
                },
                prediction_snapshot={},
            )
        )
        await session.commit()

        service = RuntimeService(session)
        prediction_set = await service.generate_prediction_set(
            loop_id=ctx.loop.id,
            payload={"source_step_id": str(ctx.score_step.id)},
            actor_user_id=ctx.actor.id,
        )
        result = await service.apply_prediction_set(
            prediction_set_id=prediction_set.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )
        assert result["applied_count"] == 0

        draft_row = await session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == ctx.project.id,
                AnnotationDraft.sample_id == ctx.sample.id,
                AnnotationDraft.user_id == ctx.actor.id,
                AnnotationDraft.branch_name == "master",
            )
        )
        assert draft_row.one_or_none() is None
