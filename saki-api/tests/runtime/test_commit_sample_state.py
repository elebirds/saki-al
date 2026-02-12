from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
from saki_api.api.api_v1.endpoints.l2.annotation import sync_working_to_draft
from saki_api.db.session import _session_ctx
from saki_api.models.enums import AuthorType, CommitSampleReviewState, TaskType
from saki_api.models.storage.dataset import Dataset
from saki_api.models.storage.sample import Sample
from saki_api.models.project.branch import Branch
from saki_api.models.project.commit import Commit
from saki_api.models.project.commit_sample_state import CommitSampleState
from saki_api.models.project.project import Project, ProjectDataset
from saki_api.models.rbac.enums import RoleType
from saki_api.models.rbac.role import Role
from saki_api.models.access.user import User
from saki_api.services.annotation.draft import AnnotationDraftService
from saki_api.services.annotation.working import AnnotationWorkingService
from saki_api.services.project.project import ProjectService

PROJECT_OWNER_ROLE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "preset-role.project_owner")


@pytest.fixture
async def commit_sample_state_env(tmp_path):
    db_path = tmp_path / "commit_sample_state.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_commit_from_empty_draft_marks_sample_as_empty_confirmed(commit_sample_state_env):
    session_local = commit_sample_state_env
    async with session_local() as session:
        owner_role = Role(
            id=PROJECT_OWNER_ROLE_ID,
            name="project_owner",
            display_name="Project Owner",
            description="project owner",
            type=RoleType.RESOURCE,
            color="red",
            is_supremo=True,
            is_system=True,
            sort_order=0,
        )
        user = User(email="annotator@example.com", hashed_password="hashed", full_name="Annotator")
        session.add(owner_role)
        session.add(user)
        await session.flush()

        dataset = Dataset(name="dataset-a", description="dataset", owner_id=user.id)
        session.add(dataset)
        await session.flush()

        draft_service = AnnotationDraftService(session)
        project_service = ProjectService(session)
        project = Project(name="p", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()
        session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))
        initial_commit = Commit(
            project_id=project.id,
            parent_id=None,
            message="Initial commit",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={"sample_count": 0, "annotation_count": 0},
            commit_hash="init",
        )
        session.add(initial_commit)
        await session.flush()
        session.add(
            Branch(
                project_id=project.id,
                name="master",
                head_commit_id=initial_commit.id,
                description="master",
                is_protected=True,
            )
        )
        sample = Sample(dataset_id=dataset.id, name="sample-a", asset_group={})
        session.add(sample)
        await session.flush()

        token = _session_ctx.set(session)
        try:
            await draft_service.upsert_draft(
                project_id=project.id,
                sample_id=sample.id,
                user_id=user.id,
                branch_name="master",
                payload={"annotations": [], "meta": {"reviewed_empty": True}},
            )
            commit, _ = await draft_service.commit_from_drafts(
                project_id=project.id,
                user_id=user.id,
                branch_name="master",
                commit_message="empty-review",
            )
        finally:
            _session_ctx.reset(token)

        states = (
            await session.exec(
                select(CommitSampleState).where(
                    CommitSampleState.commit_id == commit.id,
                    CommitSampleState.sample_id == sample.id,
                )
            )
        ).all()
        assert len(states) == 1
        assert states[0].state == CommitSampleReviewState.EMPTY_CONFIRMED

        page_labeled = await project_service.list_project_samples_page(
            project_id=project.id,
            dataset_id=dataset.id,
            current_user_id=user.id,
            branch_name="master",
            q=None,
            status="labeled",
            sort_by="createdAt",
            sort_order="desc",
            page=1,
            limit=20,
        )
        assert len(page_labeled.samples) == 1
        assert page_labeled.samples[0].id == sample.id
        assert page_labeled.annotation_counts.get(sample.id, 0) == 0
        assert page_labeled.review_states[sample.id] == CommitSampleReviewState.EMPTY_CONFIRMED

        page_unlabeled = await project_service.list_project_samples_page(
            project_id=project.id,
            dataset_id=dataset.id,
            current_user_id=user.id,
            branch_name="master",
            q=None,
            status="unlabeled",
            sort_by="createdAt",
            sort_order="desc",
            page=1,
            limit=20,
        )
        assert len(page_unlabeled.samples) == 0


@pytest.mark.anyio
async def test_sync_working_to_draft_review_empty_promotes_non_dirty_snapshot(commit_sample_state_env):
    session_local = commit_sample_state_env
    async with session_local() as session:
        owner_role = Role(
            id=PROJECT_OWNER_ROLE_ID,
            name="project_owner",
            display_name="Project Owner",
            description="project owner",
            type=RoleType.RESOURCE,
            color="red",
            is_supremo=True,
            is_system=True,
            sort_order=0,
        )
        user = User(email="annotator2@example.com", hashed_password="hashed", full_name="Annotator2")
        session.add(owner_role)
        session.add(user)
        await session.flush()

        dataset = Dataset(name="dataset-b", description="dataset", owner_id=user.id)
        session.add(dataset)
        await session.flush()

        project = Project(name="p2", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()
        session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))
        initial_commit = Commit(
            project_id=project.id,
            parent_id=None,
            message="Initial commit",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={"sample_count": 0, "annotation_count": 0},
            commit_hash="init",
        )
        session.add(initial_commit)
        await session.flush()
        session.add(
            Branch(
                project_id=project.id,
                name="master",
                head_commit_id=initial_commit.id,
                description="master",
                is_protected=True,
            )
        )

        sample = Sample(dataset_id=dataset.id, name="sample-b", asset_group={})
        session.add(sample)
        await session.flush()

        working_service = AnnotationWorkingService()
        await working_service.set_snapshot(
            project_id=project.id,
            sample_id=sample.id,
            user_id=user.id,
            branch_name="master",
            payload={"annotations": [], "meta": {}},
            dirty=0,
        )

        draft_service = AnnotationDraftService(session)
        token = _session_ctx.set(session)
        try:
            draft = await sync_working_to_draft(
                project_id=project.id,
                sample_id=sample.id,
                branch_name="master",
                review_empty=True,
                working_service=working_service,
                draft_service=draft_service,
                current_user_id=user.id,
            )
        finally:
            _session_ctx.reset(token)

        assert draft is not None
        payload = draft.payload or {}
        assert payload.get("annotations") == []
        assert payload.get("meta", {}).get("reviewed_empty") is True

        snapshot = await working_service.get_snapshot(
            project_id=project.id,
            sample_id=sample.id,
            user_id=user.id,
            branch_name="master",
        )
        assert snapshot is None
