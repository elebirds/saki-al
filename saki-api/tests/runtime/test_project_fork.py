from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
from saki_api.db.session import _session_ctx
from saki_api.models.enums import AnnotationSource, AnnotationType, AuthorType, TaskType
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import ProjectDataset
from saki_api.models.rbac.enums import ResourceType, RoleType
from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.models.rbac.role import Role
from saki_api.models.user import User
from saki_api.schemas.project import ProjectForkCreate
from saki_api.services.project import ProjectService

PROJECT_OWNER_ROLE_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "preset-role.project_owner")


@pytest.fixture
async def project_fork_env(tmp_path):
    db_path = tmp_path / "project_fork.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_project_fork_copies_all_branches_and_graph(project_fork_env):
    session_local = project_fork_env
    async with session_local() as session:
        source_user = User(email="source@example.com", hashed_password="hashed", full_name="source")
        fork_user = User(email="forker@example.com", hashed_password="hashed", full_name="forker")
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
        session.add(source_user)
        session.add(fork_user)
        session.add(owner_role)
        await session.flush()

        dataset = Dataset(
            name="dataset-a",
            description="dataset",
            owner_id=source_user.id,
        )
        session.add(dataset)
        await session.flush()

        service = ProjectService(session)
        token = _session_ctx.set(session)
        try:
            source_project = await service.initialize_project(
                name="source-project",
                task_type=TaskType.DETECTION,
                dataset_ids=[dataset.id],
                user_id=source_user.id,
                description="source desc",
                config={"k": "v"},
            )

            master_branch = (
                await session.exec(
                    select(Branch).where(
                        Branch.project_id == source_project.id,
                        Branch.name == "master",
                    )
                )
            ).one()
            root_commit_id = master_branch.head_commit_id

            label = Label(project_id=source_project.id, name="car", color="#ff0000")
            session.add(label)
            await session.flush()

            sample = Sample(dataset_id=dataset.id, name="sample-1", asset_group={})
            session.add(sample)
            await session.flush()

            ann1 = Annotation(
                sample_id=sample.id,
                label_id=label.id,
                project_id=source_project.id,
                group_id=uuid.uuid4(),
                lineage_id=uuid.uuid4(),
                data={"x": 1},
                source=AnnotationSource.MANUAL,
                type=AnnotationType.RECT,
            )
            session.add(ann1)
            await session.flush()

            ann2 = Annotation(
                sample_id=sample.id,
                label_id=label.id,
                project_id=source_project.id,
                group_id=ann1.group_id,
                lineage_id=ann1.lineage_id,
                parent_id=ann1.id,
                data={"x": 2},
                source=AnnotationSource.MANUAL,
                type=AnnotationType.RECT,
            )
            session.add(ann2)
            await session.flush()

            commit2 = Commit(
                project_id=source_project.id,
                parent_id=root_commit_id,
                message="update-1",
                author_type=AuthorType.USER,
                author_id=source_user.id,
                stats={"annotation_count": 1},
            )
            session.add(commit2)
            await session.flush()

            master_branch.head_commit_id = commit2.id
            session.add(master_branch)
            session.add(
                Branch(
                    project_id=source_project.id,
                    name="dev",
                    head_commit_id=root_commit_id,
                    description="dev",
                    is_protected=False,
                )
            )
            session.add(
                CommitAnnotationMap(
                    commit_id=root_commit_id,
                    sample_id=sample.id,
                    annotation_id=ann1.id,
                    project_id=source_project.id,
                )
            )
            session.add(
                CommitAnnotationMap(
                    commit_id=commit2.id,
                    sample_id=sample.id,
                    annotation_id=ann2.id,
                    project_id=source_project.id,
                )
            )
            await session.flush()

            forked_project = await service.fork_project(
                source_project_id=source_project.id,
                payload=ProjectForkCreate(name="forked-project"),
                user_id=fork_user.id,
            )
        finally:
            _session_ctx.reset(token)

        source_dataset_links = (
            await session.exec(select(ProjectDataset).where(ProjectDataset.project_id == source_project.id))
        ).all()
        fork_dataset_links = (
            await session.exec(select(ProjectDataset).where(ProjectDataset.project_id == forked_project.id))
        ).all()
        assert len(source_dataset_links) == len(fork_dataset_links) == 1
        assert fork_dataset_links[0].dataset_id == dataset.id

        source_labels = (await session.exec(select(Label).where(Label.project_id == source_project.id))).all()
        fork_labels = (await session.exec(select(Label).where(Label.project_id == forked_project.id))).all()
        assert len(source_labels) == len(fork_labels) == 1
        assert fork_labels[0].name == source_labels[0].name
        assert fork_labels[0].id != source_labels[0].id

        source_commits = (await session.exec(select(Commit).where(Commit.project_id == source_project.id))).all()
        fork_commits = (await session.exec(select(Commit).where(Commit.project_id == forked_project.id))).all()
        assert len(source_commits) == len(fork_commits) == 2
        fork_commit_by_message = {item.message: item for item in fork_commits}
        assert fork_commit_by_message["Initial commit"].parent_id is None
        assert fork_commit_by_message["update-1"].parent_id == fork_commit_by_message["Initial commit"].id

        source_branches = (await session.exec(select(Branch).where(Branch.project_id == source_project.id))).all()
        fork_branches = (await session.exec(select(Branch).where(Branch.project_id == forked_project.id))).all()
        assert {item.name for item in source_branches} == {item.name for item in fork_branches}
        fork_branch_head = {item.name: item.head_commit_id for item in fork_branches}
        assert fork_branch_head["master"] == fork_commit_by_message["update-1"].id
        assert fork_branch_head["dev"] == fork_commit_by_message["Initial commit"].id

        source_annotations = (
            await session.exec(select(Annotation).where(Annotation.project_id == source_project.id))
        ).all()
        fork_annotations = (
            await session.exec(select(Annotation).where(Annotation.project_id == forked_project.id))
        ).all()
        assert len(source_annotations) == len(fork_annotations) == 2
        fork_ann_by_x = {int(item.data.get("x")): item for item in fork_annotations}
        assert fork_ann_by_x[2].parent_id == fork_ann_by_x[1].id
        assert fork_ann_by_x[1].label_id == fork_labels[0].id

        source_camap = (
            await session.exec(select(CommitAnnotationMap).where(CommitAnnotationMap.project_id == source_project.id))
        ).all()
        fork_camap = (
            await session.exec(select(CommitAnnotationMap).where(CommitAnnotationMap.project_id == forked_project.id))
        ).all()
        assert len(source_camap) == len(fork_camap) == 2
        fork_commit_ids = {item.id for item in fork_commits}
        fork_annotation_ids = {item.id for item in fork_annotations}
        assert all(item.commit_id in fork_commit_ids for item in fork_camap)
        assert all(item.annotation_id in fork_annotation_ids for item in fork_camap)

        fork_owner_member = (
            await session.exec(
                select(ResourceMember).where(
                    ResourceMember.resource_type == ResourceType.PROJECT,
                    ResourceMember.resource_id == forked_project.id,
                    ResourceMember.user_id == fork_user.id,
                )
            )
        ).first()
        assert fork_owner_member is not None

        assert forked_project.config["fork_meta"]["source_project_id"] == str(source_project.id)
        assert forked_project.config["fork_meta"]["all_branches"] is True
