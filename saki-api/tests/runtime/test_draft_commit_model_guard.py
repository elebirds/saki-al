from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.annotation.service.draft import AnnotationDraftService
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.shared.modeling.enums import AuthorType, TaskType
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@pytest.fixture
async def draft_guard_env(tmp_path):
    db_path = tmp_path / "draft_guard.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_project_context(session: AsyncSession):
    user = User(email=f"guard-{uuid.uuid4()}@example.com", hashed_password="hashed")
    session.add(user)
    await session.flush()

    dataset = Dataset(name=f"dataset-{uuid.uuid4()}", owner_id=user.id)
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

    label = Label(project_id=project.id, name="car", color="#ff0000", sort_order=1)
    session.add(label)
    await session.commit()

    return {
        "user": user,
        "project": project,
        "sample": sample,
        "label": label,
    }


def _rect_annotation_payload(*, project_id: uuid.UUID, sample_id: uuid.UUID, label_id: uuid.UUID, source: str, group_id: str):
    return {
        "id": str(uuid.uuid4()),
        "project_id": str(project_id),
        "sample_id": str(sample_id),
        "label_id": str(label_id),
        "group_id": group_id,
        "lineage_id": group_id,
        "view_role": "main",
        "type": "rect",
        "source": source,
        "geometry": {"rect": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 40.0}},
        "attrs": {},
        "confidence": 0.9,
    }


@pytest.mark.anyio
async def test_commit_from_drafts_model_only_returns_400_and_keeps_draft(draft_guard_env):
    session_local = draft_guard_env
    async with session_local() as session:
        ctx = await _seed_project_context(session)
        draft_service = AnnotationDraftService(session)

        group_id = str(uuid.uuid4())
        await draft_service.upsert_draft(
            project_id=ctx["project"].id,
            sample_id=ctx["sample"].id,
            user_id=ctx["user"].id,
            branch_name="master",
            payload={
                "annotations": [
                    _rect_annotation_payload(
                        project_id=ctx["project"].id,
                        sample_id=ctx["sample"].id,
                        label_id=ctx["label"].id,
                        source="model",
                        group_id=group_id,
                    )
                ],
                "meta": {},
            },
        )

        with pytest.raises(BadRequestAppException):
            await draft_service.commit_from_drafts(
                project_id=ctx["project"].id,
                user_id=ctx["user"].id,
                branch_name="master",
                commit_message="model-only",
            )

        draft_rows = list(
            (
                await session.exec(
                    select(AnnotationDraft).where(
                        AnnotationDraft.project_id == ctx["project"].id,
                        AnnotationDraft.sample_id == ctx["sample"].id,
                        AnnotationDraft.user_id == ctx["user"].id,
                        AnnotationDraft.branch_name == "master",
                    )
                )
            ).all()
        )
        assert len(draft_rows) == 1


@pytest.mark.anyio
async def test_commit_from_drafts_model_group_blocks_same_group_system(draft_guard_env):
    session_local = draft_guard_env
    async with session_local() as session:
        ctx = await _seed_project_context(session)
        draft_service = AnnotationDraftService(session)

        group_id = str(uuid.uuid4())
        await draft_service.upsert_draft(
            project_id=ctx["project"].id,
            sample_id=ctx["sample"].id,
            user_id=ctx["user"].id,
            branch_name="master",
            payload={
                "annotations": [
                    _rect_annotation_payload(
                        project_id=ctx["project"].id,
                        sample_id=ctx["sample"].id,
                        label_id=ctx["label"].id,
                        source="model",
                        group_id=group_id,
                    ),
                    _rect_annotation_payload(
                        project_id=ctx["project"].id,
                        sample_id=ctx["sample"].id,
                        label_id=ctx["label"].id,
                        source="system",
                        group_id=group_id,
                    ),
                ],
                "meta": {},
            },
        )

        with pytest.raises(BadRequestAppException):
            await draft_service.commit_from_drafts(
                project_id=ctx["project"].id,
                user_id=ctx["user"].id,
                branch_name="master",
                commit_message="model-system-group",
            )

        draft_rows = list(
            (
                await session.exec(
                    select(AnnotationDraft).where(
                        AnnotationDraft.project_id == ctx["project"].id,
                        AnnotationDraft.sample_id == ctx["sample"].id,
                        AnnotationDraft.user_id == ctx["user"].id,
                        AnnotationDraft.branch_name == "master",
                    )
                )
            ).all()
        )
        assert len(draft_rows) == 1


@pytest.mark.anyio
async def test_commit_from_drafts_confirmed_model_can_commit(draft_guard_env):
    session_local = draft_guard_env
    async with session_local() as session:
        ctx = await _seed_project_context(session)
        draft_service = AnnotationDraftService(session)

        group_id = str(uuid.uuid4())
        await draft_service.upsert_draft(
            project_id=ctx["project"].id,
            sample_id=ctx["sample"].id,
            user_id=ctx["user"].id,
            branch_name="master",
            payload={
                "annotations": [
                    _rect_annotation_payload(
                        project_id=ctx["project"].id,
                        sample_id=ctx["sample"].id,
                        label_id=ctx["label"].id,
                        source="confirmed_model",
                        group_id=group_id,
                    )
                ],
                "meta": {},
            },
        )

        commit, used_sample_ids = await draft_service.commit_from_drafts(
            project_id=ctx["project"].id,
            user_id=ctx["user"].id,
            branch_name="master",
            commit_message="confirmed-model",
        )

        assert len(used_sample_ids) == 1
        assert used_sample_ids[0] == ctx["sample"].id

        commit_rows = list(
            (
                await session.exec(
                    select(CommitAnnotationMap.annotation_id).where(
                        CommitAnnotationMap.commit_id == commit.id,
                        CommitAnnotationMap.sample_id == ctx["sample"].id,
                    )
                )
            ).all()
        )
        assert len(commit_rows) == 1
        ann_id = commit_rows[0]
        annotation = await session.get(Annotation, ann_id)
        assert annotation is not None
        source_text = str(annotation.source.value if hasattr(annotation.source, "value") else annotation.source)
        assert source_text == "confirmed_model"

        remaining_drafts = list(
            (
                await session.exec(
                    select(AnnotationDraft).where(
                        AnnotationDraft.project_id == ctx["project"].id,
                        AnnotationDraft.sample_id == ctx["sample"].id,
                        AnnotationDraft.user_id == ctx["user"].id,
                        AnnotationDraft.branch_name == "master",
                    )
                )
            ).all()
        )
        assert remaining_drafts == []
