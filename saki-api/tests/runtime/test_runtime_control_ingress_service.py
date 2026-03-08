from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.infra.grpc import runtime_codec
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.modules.access.domain.access.user import User
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    CommitSampleReviewState,
    LoopLifecycle,
    LoopMode,
    LoopPhase,
    RoundStatus,
    RuntimeTaskKind,
    RuntimeTaskStatus,
    RuntimeTaskType,
    StepType,
    TaskType,
)
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@pytest.fixture
async def runtime_ingress_env(tmp_path):
    db_path = tmp_path / "runtime_ingress_service.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_manual_runtime_scope(
    session: AsyncSession,
    *,
    step_type: StepType,
) -> dict[str, str]:
    project = Project(name=f"ingress-project-{uuid.uuid4().hex[:8]}", task_type=TaskType.DETECTION, config={})
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

    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        full_name="seed-user",
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()

    dataset = Dataset(owner_id=user.id, name=f"dataset-{uuid.uuid4().hex[:6]}")
    session.add(dataset)
    await session.flush()
    session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))
    await session.flush()

    sample_labeled = Sample(dataset_id=dataset.id, name="sample-labeled", asset_group={}, meta_info={})
    sample_empty = Sample(dataset_id=dataset.id, name="sample-empty", asset_group={}, meta_info={})
    sample_unreviewed = Sample(dataset_id=dataset.id, name="sample-unreviewed", asset_group={}, meta_info={})
    sample_ann_fallback = Sample(dataset_id=dataset.id, name="sample-ann-fallback", asset_group={}, meta_info={})
    session.add_all([sample_labeled, sample_empty, sample_unreviewed, sample_ann_fallback])
    await session.flush()

    session.add_all(
        [
            CommitSampleState(
                commit_id=commit.id,
                sample_id=sample_labeled.id,
                project_id=project.id,
                state=CommitSampleReviewState.LABELED,
            ),
            CommitSampleState(
                commit_id=commit.id,
                sample_id=sample_empty.id,
                project_id=project.id,
                state=CommitSampleReviewState.EMPTY_CONFIRMED,
            ),
        ]
    )

    label = Label(project_id=project.id, name="label-a", color="#1890ff", sort_order=1)
    session.add(label)
    await session.flush()

    ann = Annotation(
        sample_id=sample_ann_fallback.id,
        label_id=label.id,
        project_id=project.id,
        group_id=uuid.uuid4(),
        lineage_id=uuid.uuid4(),
        geometry={"rect": {"x": 1, "y": 1, "width": 10, "height": 10}},
    )
    session.add(ann)
    await session.flush()
    session.add(
        CommitAnnotationMap(
            commit_id=commit.id,
            sample_id=sample_ann_fallback.id,
            annotation_id=ann.id,
            project_id=project.id,
        )
    )

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="manual-loop",
        mode=LoopMode.MANUAL,
        phase=LoopPhase.MANUAL_TRAIN if step_type == StepType.TRAIN else LoopPhase.MANUAL_EVAL,
        model_arch="yolo_det_v1",
        config={"reproducibility": {"global_seed": "seed"}},
        lifecycle=LoopLifecycle.RUNNING,
        max_rounds=10,
        query_batch_size=1,
        min_new_labels_per_round=1,
    )
    session.add(loop)
    await session.flush()

    round_row = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        attempt_index=1,
        mode=LoopMode.MANUAL,
        state=RoundStatus.RUNNING,
        plugin_id="yolo_det_v1",
        resolved_params={"reproducibility": {"global_seed": "seed"}},
        input_commit_id=commit.id,
    )
    session.add(round_row)
    await session.flush()

    task_type = RuntimeTaskType.TRAIN if step_type == StepType.TRAIN else RuntimeTaskType.EVAL
    task = Task(
        project_id=project.id,
        kind=RuntimeTaskKind.STEP,
        task_type=task_type,
        status=RuntimeTaskStatus.PENDING,
        plugin_id="yolo_det_v1",
        input_commit_id=commit.id,
        resolved_params={},
    )
    session.add(task)
    await session.flush()

    session.add(
        Step(
            round_id=round_row.id,
            step_type=step_type,
            round_index=1,
            step_index=1,
            task_id=task.id,
            input_commit_id=commit.id,
        )
    )

    await session.commit()
    return {
        "project_id": str(project.id),
        "commit_id": str(commit.id),
        "task_id": str(task.id),
        "sample_labeled_id": str(sample_labeled.id),
        "sample_empty_id": str(sample_empty.id),
        "sample_unreviewed_id": str(sample_unreviewed.id),
        "sample_ann_fallback_id": str(sample_ann_fallback.id),
    }


@pytest.mark.anyio
@pytest.mark.parametrize("step_type", [StepType.TRAIN, StepType.EVAL])
async def test_manual_train_eval_samples_only_exposes_reviewed_and_annotation_fallback(runtime_ingress_env, step_type):
    session_local = runtime_ingress_env
    async with session_local() as session:
        seeded = await _seed_manual_runtime_scope(session, step_type=step_type)

    service = RuntimeControlIngressService(session_local=session_local)
    batch, next_cursor = await service._query_data_batch(
        query_type=pb.SAMPLES,
        task_id=seeded["task_id"],
        project_id=uuid.UUID(seeded["project_id"]),
        commit_id=uuid.UUID(seeded["commit_id"]),
        limit=100,
        offset=0,
    )

    assert next_cursor is None
    samples = [item.sample for item in batch.items if item.WhichOneof("item") == "sample"]
    sample_ids = {item.id for item in samples}
    assert sample_ids == {
        seeded["sample_labeled_id"],
        seeded["sample_empty_id"],
        seeded["sample_ann_fallback_id"],
    }
    assert seeded["sample_unreviewed_id"] not in sample_ids

    meta_by_sample_id = {item.id: runtime_codec.struct_to_dict(item.meta) for item in samples}
    assert meta_by_sample_id[seeded["sample_labeled_id"]]["_commit_review_state"] == "labeled"
    assert meta_by_sample_id[seeded["sample_empty_id"]]["_commit_review_state"] == "empty_confirmed"
    assert "_commit_review_state" not in meta_by_sample_id[seeded["sample_ann_fallback_id"]]
