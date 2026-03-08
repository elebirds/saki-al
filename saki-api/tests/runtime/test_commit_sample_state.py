from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.annotation.api.http.annotation import sync_working_to_draft
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.infra.db.session import _session_ctx
from saki_api.modules.shared.modeling.enums import AnnotationSource, AnnotationType, AuthorType, CommitSampleReviewState, TaskType
from saki_api.modules.project.domain.label import Label
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.access.domain.rbac.enums import RoleType
from saki_api.modules.access.domain.rbac.role import Role
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.service.draft import AnnotationDraftService
from saki_api.modules.annotation.service.working import AnnotationWorkingService
from saki_api.modules.project.service.project import ProjectService

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


@pytest.mark.anyio
async def test_list_project_dataset_label_counts_changes_with_branch(commit_sample_state_env):
    session_local = commit_sample_state_env
    async with session_local() as session:
        user = User(email="label-count@example.com", hashed_password="hashed", full_name="Counter")
        session.add(user)
        await session.flush()

        dataset = Dataset(name="dataset-label-count", description="dataset", owner_id=user.id)
        session.add(dataset)
        await session.flush()

        project = Project(name="label-project", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()
        session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

        label_ship = Label(project_id=project.id, name="Ship", color="#ff0000", sort_order=1)
        label_plane = Label(project_id=project.id, name="Plane", color="#00ff00", sort_order=2)
        label_vehicle = Label(project_id=project.id, name="Vehicle", color="#0000ff", sort_order=3)
        session.add(label_ship)
        session.add(label_plane)
        session.add(label_vehicle)

        sample_a = Sample(dataset_id=dataset.id, name="a.jpg", asset_group={})
        sample_b = Sample(dataset_id=dataset.id, name="b.jpg", asset_group={})
        session.add(sample_a)
        session.add(sample_b)
        await session.flush()

        commit_master = Commit(
            project_id=project.id,
            parent_id=None,
            message="master",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
            commit_hash="master",
        )
        session.add(commit_master)
        await session.flush()
        commit_dev = Commit(
            project_id=project.id,
            parent_id=commit_master.id,
            message="dev",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
            commit_hash="dev",
        )
        session.add(commit_dev)
        await session.flush()

        session.add(Branch(project_id=project.id, name="master", head_commit_id=commit_master.id, is_protected=True))
        session.add(Branch(project_id=project.id, name="dev", head_commit_id=commit_dev.id, is_protected=False))
        await session.flush()

        def _ann(sample_id: uuid.UUID, label_id: uuid.UUID) -> Annotation:
            return Annotation(
                sample_id=sample_id,
                label_id=label_id,
                project_id=project.id,
                group_id=uuid.uuid4(),
                lineage_id=uuid.uuid4(),
                view_role="main",
                parent_id=None,
                type=AnnotationType.RECT,
                source=AnnotationSource.MANUAL,
                geometry={"rect": {"x": 1, "y": 1, "width": 10, "height": 10}},
                attrs={},
                confidence=1.0,
                annotator_id=user.id,
            )

        ann_m1 = _ann(sample_a.id, label_ship.id)
        ann_m2 = _ann(sample_b.id, label_ship.id)
        ann_m3 = _ann(sample_b.id, label_plane.id)
        ann_d1 = _ann(sample_a.id, label_ship.id)
        ann_d2 = _ann(sample_a.id, label_plane.id)
        ann_d3 = _ann(sample_b.id, label_plane.id)
        ann_d4 = _ann(sample_b.id, label_vehicle.id)
        session.add(ann_m1)
        session.add(ann_m2)
        session.add(ann_m3)
        session.add(ann_d1)
        session.add(ann_d2)
        session.add(ann_d3)
        session.add(ann_d4)
        await session.flush()

        session.add(CommitAnnotationMap(
            commit_id=commit_master.id, sample_id=sample_a.id, annotation_id=ann_m1.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_master.id, sample_id=sample_b.id, annotation_id=ann_m2.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_master.id, sample_id=sample_b.id, annotation_id=ann_m3.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_dev.id, sample_id=sample_a.id, annotation_id=ann_d1.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_dev.id, sample_id=sample_a.id, annotation_id=ann_d2.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_dev.id, sample_id=sample_b.id, annotation_id=ann_d3.id, project_id=project.id
        ))
        session.add(CommitAnnotationMap(
            commit_id=commit_dev.id, sample_id=sample_b.id, annotation_id=ann_d4.id, project_id=project.id
        ))
        await session.commit()

        service = ProjectService(session)

        rows_master = await service.list_project_dataset_label_counts(
            project_id=project.id,
            dataset_id=dataset.id,
            branch_name="master",
        )
        rows_dev = await service.list_project_dataset_label_counts(
            project_id=project.id,
            dataset_id=dataset.id,
            branch_name="dev",
        )

        assert [row["label_name"] for row in rows_master] == ["Ship", "Plane", "Vehicle"]
        assert [row["annotation_count"] for row in rows_master] == [2, 1, 0]
        assert [row["annotation_count"] for row in rows_dev] == [1, 2, 1]


@pytest.mark.anyio
async def test_list_project_dataset_label_counts_returns_zero_for_labels_without_annotations(commit_sample_state_env):
    session_local = commit_sample_state_env
    async with session_local() as session:
        user = User(email="label-zero@example.com", hashed_password="hashed", full_name="Zero")
        session.add(user)
        await session.flush()

        dataset = Dataset(name="dataset-zero", description="dataset", owner_id=user.id)
        session.add(dataset)
        await session.flush()

        project = Project(name="zero-project", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()
        session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

        label_a = Label(project_id=project.id, name="A", color="#111111", sort_order=1)
        label_b = Label(project_id=project.id, name="B", color="#222222", sort_order=2)
        session.add(label_a)
        session.add(label_b)

        commit_master = Commit(
            project_id=project.id,
            parent_id=None,
            message="master",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
            commit_hash="master",
        )
        session.add(commit_master)
        await session.flush()
        session.add(Branch(project_id=project.id, name="master", head_commit_id=commit_master.id, is_protected=True))
        await session.commit()

        service = ProjectService(session)
        rows = await service.list_project_dataset_label_counts(
            project_id=project.id,
            dataset_id=dataset.id,
            branch_name="master",
        )

        assert [row["label_name"] for row in rows] == ["A", "B"]
        assert [row["annotation_count"] for row in rows] == [0, 0]
