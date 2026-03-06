from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.core.exceptions import (
    BadRequestAppException,
    ConflictAppException,
    ForbiddenAppException,
)
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project
from saki_api.modules.project.service.sample import SampleService
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.domain.step_candidate_item import TaskCandidateItem
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    CommitSampleReviewState,
    StepType,
    TaskType,
)
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@dataclass
class SampleDeleteContext:
    owner: User
    actor: User
    dataset: Dataset
    sample: Sample
    project: Project
    label: Label
    commit: Commit
    round_: Round
    step: Step


@pytest.fixture
async def sample_delete_env(tmp_path, monkeypatch):
    async def _fake_scan_working_keys(self, sample_id: uuid.UUID) -> list[str]:
        return []

    monkeypatch.setattr(SampleService, "_scan_working_snapshot_keys", _fake_scan_working_keys)

    db_path = tmp_path / "sample_delete_policy.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


def _scalar_count(value: object) -> int:
    if isinstance(value, (tuple, list)):
        if not value:
            return 0
        value = value[0]
    return int(value or 0)


async def _count_by_sample(session: AsyncSession, model, sample_id: uuid.UUID) -> int:
    row = (
        await session.exec(select(func.count()).select_from(model).where(model.sample_id == sample_id))
    ).one()
    return _scalar_count(row)


async def _seed_context(session: AsyncSession) -> SampleDeleteContext:
    owner = User(email="owner@example.com", hashed_password="hashed-owner")
    actor = User(email="actor@example.com", hashed_password="hashed-actor")
    session.add(owner)
    session.add(actor)
    await session.flush()

    dataset = Dataset(name="dataset-delete-policy", owner_id=owner.id)
    session.add(dataset)
    await session.flush()

    sample = Sample(dataset_id=dataset.id, name="sample-a", asset_group={})
    session.add(sample)
    await session.flush()

    project = Project(name="project-delete-policy", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    label = Label(name="label-a", project_id=project.id)
    commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={"sample_count": 1, "annotation_count": 1},
        commit_hash="init-delete-policy",
    )
    session.add(label)
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
        name="loop-delete-policy",
        query_strategy="random",
        model_arch="test-model",
    )
    session.add(loop)
    await session.flush()

    round_ = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
    )
    session.add(round_)
    await session.flush()

    step = Step(
        round_id=round_.id,
        step_type=StepType.SELECT,
        round_index=1,
        step_index=1,
    )
    session.add(step)
    await session.flush()

    task = Task(project_id=project.id)
    session.add(task)
    await session.flush()
    step.task_id = task.id
    session.add(step)
    await session.flush()

    return SampleDeleteContext(
        owner=owner,
        actor=actor,
        dataset=dataset,
        sample=sample,
        project=project,
        label=label,
        commit=commit,
        round_=round_,
        step=step,
    )


async def _create_committed_refs(session: AsyncSession, ctx: SampleDeleteContext) -> Annotation:
    annotation = Annotation(
        sample_id=ctx.sample.id,
        label_id=ctx.label.id,
        project_id=ctx.project.id,
        group_id=uuid.uuid4(),
        lineage_id=uuid.uuid4(),
        geometry={"rect": {"x": 1, "y": 1, "width": 10, "height": 10}},
    )
    session.add(annotation)
    await session.flush()

    camap = CommitAnnotationMap(
        commit_id=ctx.commit.id,
        sample_id=ctx.sample.id,
        annotation_id=annotation.id,
        project_id=ctx.project.id,
    )
    sample_state = CommitSampleState(
        commit_id=ctx.commit.id,
        sample_id=ctx.sample.id,
        project_id=ctx.project.id,
        state=CommitSampleReviewState.LABELED,
    )
    session.add(camap)
    session.add(sample_state)
    await session.flush()
    return annotation


async def _create_transient_refs(session: AsyncSession, ctx: SampleDeleteContext) -> None:
    draft = AnnotationDraft(
        project_id=ctx.project.id,
        sample_id=ctx.sample.id,
        user_id=ctx.owner.id,
        branch_name="master",
        payload={"annotations": []},
    )
    candidate_item = TaskCandidateItem(
        task_id=ctx.step.task_id,
        sample_id=ctx.sample.id,
        rank=1,
        score=0.8,
    )
    session.add(draft)
    session.add(candidate_item)
    await session.flush()


@pytest.mark.anyio
async def test_delete_sample_without_committed_refs_cleans_transient_refs(sample_delete_env):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        draft = AnnotationDraft(
            project_id=ctx.project.id,
            sample_id=ctx.sample.id,
            user_id=ctx.owner.id,
            branch_name="master",
            payload={"annotations": []},
        )
        session.add(draft)
        await session.flush()

        service = SampleService(session)
        result = await service.delete_sample_with_policy(
            dataset_id=ctx.dataset.id,
            sample_id=ctx.sample.id,
            actor_user_id=ctx.owner.id,
            force=False,
        )

        assert result["ok"] is True
        assert result["forced"] is False
        assert await session.get(Sample, ctx.sample.id) is None
        assert await _count_by_sample(session, AnnotationDraft, ctx.sample.id) == 0


@pytest.mark.anyio
async def test_delete_sample_with_committed_refs_returns_conflict_without_data_change(sample_delete_env):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        await _create_committed_refs(session, ctx)

        service = SampleService(session)
        with pytest.raises(ConflictAppException) as exc_info:
            await service.delete_sample_with_policy(
                dataset_id=ctx.dataset.id,
                sample_id=ctx.sample.id,
                actor_user_id=ctx.owner.id,
                force=False,
            )

        payload = exc_info.value.data or {}
        assert payload.get("reason") == "sample_in_use"
        assert payload.get("confirmation_required") is True
        assert payload.get("can_force") is True
        assert await session.get(Sample, ctx.sample.id) is not None
        assert await _count_by_sample(session, Annotation, ctx.sample.id) == 1
        assert await _count_by_sample(session, CommitAnnotationMap, ctx.sample.id) == 1
        assert await _count_by_sample(session, CommitSampleState, ctx.sample.id) == 1


@pytest.mark.anyio
async def test_force_delete_with_owner_cleans_all_refs(sample_delete_env):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        await _create_committed_refs(session, ctx)
        await _create_transient_refs(session, ctx)

        service = SampleService(session)
        result = await service.delete_sample_with_policy(
            dataset_id=ctx.dataset.id,
            sample_id=ctx.sample.id,
            actor_user_id=ctx.owner.id,
            force=True,
        )

        assert result["ok"] is True
        assert result["forced"] is True
        assert await session.get(Sample, ctx.sample.id) is None
        assert await _count_by_sample(session, Annotation, ctx.sample.id) == 0
        assert await _count_by_sample(session, CommitAnnotationMap, ctx.sample.id) == 0
        assert await _count_by_sample(session, CommitSampleState, ctx.sample.id) == 0
        assert await _count_by_sample(session, AnnotationDraft, ctx.sample.id) == 0
        assert await _count_by_sample(session, TaskCandidateItem, ctx.sample.id) == 0


@pytest.mark.anyio
async def test_force_delete_without_owner_or_super_admin_returns_forbidden(sample_delete_env):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        await _create_committed_refs(session, ctx)

        service = SampleService(session)
        with pytest.raises(ForbiddenAppException):
            await service.delete_sample_with_policy(
                dataset_id=ctx.dataset.id,
                sample_id=ctx.sample.id,
                actor_user_id=ctx.actor.id,
                force=True,
            )

        assert await session.get(Sample, ctx.sample.id) is not None
        assert await _count_by_sample(session, Annotation, ctx.sample.id) == 1


@pytest.mark.anyio
async def test_delete_sample_with_dataset_mismatch_returns_bad_request(sample_delete_env):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        another_dataset = Dataset(name="another-dataset", owner_id=ctx.owner.id)
        session.add(another_dataset)
        await session.flush()

        service = SampleService(session)
        with pytest.raises(BadRequestAppException):
            await service.delete_sample_with_policy(
                dataset_id=another_dataset.id,
                sample_id=ctx.sample.id,
                actor_user_id=ctx.owner.id,
                force=False,
            )


@pytest.mark.anyio
async def test_delete_sample_integrity_error_is_converted_to_conflict(sample_delete_env, monkeypatch):
    session_local = sample_delete_env
    async with session_local() as session:
        ctx = await _seed_context(session)
        service = SampleService(session)

        async def _raise_integrity_error(sample_id: uuid.UUID) -> dict[str, dict[str, int]]:
            raise IntegrityError(
                "DELETE FROM sample WHERE sample.id = :id",
                {"id": str(sample_id)},
                Exception("simulated fk violation"),
            )

        monkeypatch.setattr(service, "_cleanup_sample_refs", _raise_integrity_error)

        with pytest.raises(ConflictAppException) as exc_info:
            await service.delete_sample_with_policy(
                dataset_id=ctx.dataset.id,
                sample_id=ctx.sample.id,
                actor_user_id=ctx.owner.id,
                force=False,
            )

        payload = exc_info.value.data or {}
        assert payload.get("reason") == "sample_in_use"
        assert payload.get("confirmation_required") is True
        assert await session.get(Sample, ctx.sample.id) is not None
