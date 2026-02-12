"""
Project Service - Business logic for Project operations.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, List, Sequence, Set

from sqlalchemy import asc, desc, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import (
    DataAlreadyExistsAppException,
    NotFoundAppException,
    BadRequestAppException,
    ForbiddenAppException,
)
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.presets import PROJECT_OWNER_ROLE_ID, PROJECT_ROLE_NAME_PREFIX
from saki_api.db.transaction import transactional
from saki_api.models import ResourceType, Permissions
from saki_api.models.enums import AuthorType, CommitSampleReviewState, ProjectStatus
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.annotation_draft import AnnotationDraft
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit_sample_state import CommitSampleState
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import Project, ProjectDataset
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_task import JobTask
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.task_candidate_item import TaskCandidateItem
from saki_api.models.rbac.enums import RoleType
from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.models.rbac.role import Role
from saki_api.repositories.annotation.annotation import AnnotationRepository
from saki_api.repositories.project.branch import BranchRepository
from saki_api.repositories.project.dataset import DatasetRepository
from saki_api.repositories.project.label import LabelRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.repositories.query import Pagination
from saki_api.repositories.project.commit_sample_state import CommitSampleStateRepository
from saki_api.repositories.access.resource_member import ResourceMemberRepository
from saki_api.repositories.access.role import RoleRepository
from saki_api.schemas.project import ProjectCreate, ProjectForkCreate, ProjectUpdate
from saki_api.schemas.access.resource_member import ResourceMemberCreateRequest, ResourceMemberRead, \
    ResourceMemberUpdateRequest
from saki_api.services.base import BaseService
from saki_api.services.annotation.camap import CAMapService
from saki_api.services.project.commit_hash import refresh_commit_hash
from saki_api.services.access.user import UserService


@dataclass
class ProjectSamplePage:
    samples: list[Sample]
    total: int
    offset: int
    limit: int
    annotation_counts: dict[uuid.UUID, int]
    drafts_by_sample: set[uuid.UUID]
    review_states: dict[uuid.UUID, CommitSampleReviewState]


class ProjectService(BaseService[Project, ProjectRepository, ProjectCreate, ProjectUpdate]):
    """
    Service for managing Projects.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Project, ProjectRepository, session)
        self.session = session
        self.resource_member_repo = ResourceMemberRepository(session)
        self.dataset_repo = DatasetRepository(session)
        self.label_repo = LabelRepository(session)
        self.role_repo = RoleRepository(session)

    async def _is_supremo_role(self, role_id: uuid.UUID) -> bool:
        role = await self.role_repo.get_by_id(role_id)
        if role is None:
            raise NotFoundAppException(f"Role {role_id} not found")
        return bool(role.is_supremo)

    async def _ensure_dataset_link_permission(
            self,
            *,
            actor_user_id: uuid.UUID,
            dataset_id: uuid.UUID,
    ) -> None:
        checker = PermissionChecker(self.session)
        allowed = await checker.check(
            user_id=actor_user_id,
            permission=Permissions.DATASET_LINK_PROJECT,
            resource_type=ResourceType.DATASET,
            resource_id=str(dataset_id),
        )
        if not allowed:
            raise ForbiddenAppException(
                f"Permission denied: dataset {dataset_id} cannot be linked/unlinked for this user"
            )

    @transactional
    async def initialize_project(
            self,
            name: str,
            task_type: str,
            dataset_ids: List[uuid.UUID],
            user_id: uuid.UUID,
            description: str | None = None,
            config: dict | None = None,
    ) -> Project:
        """
        Initialize a new project with master branch and initial commit.

        This is the core L2 initialization workflow that sets up:
        1. Create Project
        2. Link datasets
        3. Create initial commit (parent_id=None, author_type=SYSTEM)
        4. Create master branch pointing to initial commit
        5. Assign owner role to creator

        Args:
            name: Project name
            task_type: ML task type (classification, detection, etc.)
            dataset_ids: List of dataset IDs to link
            user_id: Creator user ID
            description: Optional description
            config: Optional project configuration

        Returns:
            Created project with all L2 structures initialized
        """
        # 1. Verify datasets exist
        dataset_type = None
        for dataset_id in dataset_ids:
            dataset = await self.dataset_repo.get_by_id(dataset_id)
            if not dataset:
                raise NotFoundAppException(f"Dataset {dataset_id} not found")
            await self._ensure_dataset_link_permission(actor_user_id=user_id, dataset_id=dataset_id)
            if dataset_type is None:
                dataset_type = dataset.type
            elif dataset.type != dataset_type:
                raise BadRequestAppException(
                    "All datasets linked to a project must share the same type"
                )

        # 2. Create Project
        project_data = {
            "name": name,
            "description": description,
            "task_type": task_type,
            "config": config or {},
        }
        project = Project(**project_data)
        self.session.add(project)
        await self.session.flush()
        await self.session.refresh(project)

        # 3. Link datasets
        for dataset_id in dataset_ids:
            link = ProjectDataset(project_id=project.id, dataset_id=dataset_id)
            self.session.add(link)

        # 4. Create initial commit (parent_id=None, author_type=SYSTEM)
        initial_commit = Commit(
            project_id=project.id,
            parent_id=None,
            message="Initial commit",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={"annotation_count": 0, "sample_count": 0},
            commit_hash="",
        )
        self.session.add(initial_commit)
        await self.session.flush()
        await self.session.refresh(initial_commit)
        await refresh_commit_hash(self.session, initial_commit)

        # 5. Create master branch pointing to initial commit
        master_branch = Branch(
            project_id=project.id,
            name="master",
            head_commit_id=initial_commit.id,
            description="Default branch",
            is_protected=True,
        )
        self.session.add(master_branch)
        await self.session.flush()

        # 6. Assign owner role to creator
        await self.resource_member_repo.assign_role(
            resource_type=ResourceType.PROJECT,
            resource_id=project.id,
            user_id=user_id,
            role_id=PROJECT_OWNER_ROLE_ID,
        )

        await self.session.refresh(project)
        return project

    async def get_with_relations(self, project_id: uuid.UUID) -> Project:
        """
        Get project with all L2 relations loaded.

        Args:
            project_id: Project ID

        Returns:
            Project with branches, commits, labels, datasets loaded
        """
        project = await self.repository.get_with_relations(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")
        return project

    async def get_with_counts(self, project_id: uuid.UUID) -> dict:
        """
        Get project with aggregated counts.

        Args:
            project_id: Project ID

        Returns:
            Dictionary with project data and counts
        """
        project = await self.get_by_id_or_raise(project_id)
        return {
            **project.__dict__,
            "dataset_count": await self.repository.count_datasets(project_id),
            "label_count": await self.repository.count_labels(project_id),
            "branch_count": await self.repository.count_branches(project_id),
            "commit_count": await self.repository.count_commits(project_id),
            "fork_count": await self.repository.count_forks(project_id),
        }

    async def list_in_permission_paginated(
            self,
            user_id: uuid.UUID,
            pagination: Pagination,
    ):
        return await self.repository.list_in_permission_paginated(user_id=user_id, pagination=pagination)

    async def list_in_permission(self, user_id: uuid.UUID) -> list[Project]:
        return await self.repository.list_in_permission(user_id=user_id)

    async def get_available_project_roles(self, project_id: uuid.UUID) -> list[Role]:
        await self.get_by_id_or_raise(project_id)
        roles = await self.session.exec(
            select(Role)
            .where(
                Role.type == RoleType.RESOURCE,
                Role.name.like(f"{PROJECT_ROLE_NAME_PREFIX}%"),
            )
            .order_by(Role.name)
        )
        return list(roles.all())

    @transactional
    async def set_project_status(self, project_id: uuid.UUID, status: ProjectStatus) -> Project:
        await self.get_by_id_or_raise(project_id)
        project = await self.repository.update(project_id, {"status": status})
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")
        return project

    @staticmethod
    def _deep_clone_json(value: Any) -> Any:
        return json.loads(json.dumps(value))

    async def _fork_copy_commits(
            self,
            *,
            source_project_id: uuid.UUID,
            target_project_id: uuid.UUID,
    ) -> dict[uuid.UUID, uuid.UUID]:
        source_commit_rows = await self.session.exec(
            select(Commit)
            .where(Commit.project_id == source_project_id)
            .order_by(Commit.created_at.asc())
        )
        source_commits = list(source_commit_rows.all())
        if not source_commits:
            raise BadRequestAppException("Source project has no commit history to fork")

        commit_id_map: dict[uuid.UUID, uuid.UUID] = {}
        pending_commits = {item.id: item for item in source_commits}

        while pending_commits:
            progressed = False
            for source_commit_id, source_commit in list(pending_commits.items()):
                if source_commit.parent_id and source_commit.parent_id not in commit_id_map:
                    continue
                if not source_commit.commit_hash:
                    raise BadRequestAppException(
                        f"Source commit {source_commit.id} missing commit_hash; legacy commits are not supported"
                    )

                cloned_commit = Commit(
                    project_id=target_project_id,
                    parent_id=commit_id_map.get(source_commit.parent_id),
                    message=source_commit.message,
                    author_type=source_commit.author_type,
                    author_id=source_commit.author_id,
                    stats=self._deep_clone_json(source_commit.stats or {}),
                    extra=self._deep_clone_json(source_commit.extra or {}),
                    commit_hash=source_commit.commit_hash,
                    created_at=source_commit.created_at,
                    updated_at=source_commit.updated_at,
                )
                self.session.add(cloned_commit)
                commit_id_map[source_commit_id] = cloned_commit.id
                pending_commits.pop(source_commit_id)
                progressed = True

            if not progressed:
                raise BadRequestAppException("Source commit graph is invalid (missing parent commit)")

        await self.session.flush()
        return commit_id_map

    async def _fork_copy_annotations(
            self,
            *,
            source_project_id: uuid.UUID,
            target_project_id: uuid.UUID,
            label_id_map: dict[uuid.UUID, uuid.UUID],
    ) -> dict[uuid.UUID, uuid.UUID]:
        source_annotation_rows = await self.session.exec(
            select(Annotation)
            .where(Annotation.project_id == source_project_id)
            .order_by(Annotation.created_at.asc())
        )
        source_annotations = list(source_annotation_rows.all())
        if not source_annotations:
            return {}

        annotation_id_map: dict[uuid.UUID, uuid.UUID] = {}
        pending_annotations = {item.id: item for item in source_annotations}

        while pending_annotations:
            progressed = False
            for source_annotation_id, source_annotation in list(pending_annotations.items()):
                if source_annotation.parent_id and source_annotation.parent_id not in annotation_id_map:
                    continue

                mapped_label_id = label_id_map.get(source_annotation.label_id)
                if not mapped_label_id:
                    raise BadRequestAppException(
                        f"Source annotation label {source_annotation.label_id} not found during fork"
                    )

                cloned_annotation = Annotation(
                    sample_id=source_annotation.sample_id,
                    label_id=mapped_label_id,
                    project_id=target_project_id,
                    group_id=source_annotation.group_id,
                    lineage_id=source_annotation.lineage_id,
                    view_role=source_annotation.view_role,
                    parent_id=annotation_id_map.get(source_annotation.parent_id),
                    type=source_annotation.type,
                    source=source_annotation.source,
                    data=self._deep_clone_json(source_annotation.data or {}),
                    extra=self._deep_clone_json(source_annotation.extra or {}),
                    confidence=source_annotation.confidence,
                    annotator_id=source_annotation.annotator_id,
                    created_at=source_annotation.created_at,
                    updated_at=source_annotation.updated_at,
                )
                self.session.add(cloned_annotation)
                annotation_id_map[source_annotation_id] = cloned_annotation.id
                pending_annotations.pop(source_annotation_id)
                progressed = True

            if not progressed:
                raise BadRequestAppException("Source annotation graph is invalid (missing parent annotation)")

        await self.session.flush()
        return annotation_id_map

    @transactional
    async def fork_project(
            self,
            *,
            source_project_id: uuid.UUID,
            payload: ProjectForkCreate,
            user_id: uuid.UUID,
    ) -> Project:
        source_project = await self.repository.get_by_id(source_project_id)
        if not source_project:
            raise NotFoundAppException(f"Project {source_project_id} not found")

        fork_name = str(payload.name or "").strip()
        if not fork_name:
            raise BadRequestAppException("Fork project name cannot be empty")

        cloned_config = self._deep_clone_json(source_project.config or {})
        if payload.config:
            cloned_config.update(self._deep_clone_json(payload.config))
        cloned_config["fork_meta"] = {
            "source_project_id": str(source_project_id),
            "all_branches": True,
            "forked_at": datetime.now(UTC).isoformat(),
        }

        forked_project = Project(
            name=fork_name,
            description=payload.description if payload.description is not None else source_project.description,
            task_type=source_project.task_type,
            status=ProjectStatus.ACTIVE,
            config=cloned_config,
        )
        self.session.add(forked_project)
        await self.session.flush()

        source_dataset_ids = await self.repository.get_linked_dataset_ids(source_project_id)
        for dataset_id in source_dataset_ids:
            self.session.add(ProjectDataset(project_id=forked_project.id, dataset_id=dataset_id))

        source_labels = await self.label_repo.get_by_project(source_project_id)
        label_id_map: dict[uuid.UUID, uuid.UUID] = {}
        for source_label in source_labels:
            cloned_label = Label(
                project_id=forked_project.id,
                name=source_label.name,
                color=source_label.color,
                description=source_label.description,
                sort_order=source_label.sort_order,
                shortcut=source_label.shortcut,
                created_at=source_label.created_at,
                updated_at=source_label.updated_at,
            )
            self.session.add(cloned_label)
            label_id_map[source_label.id] = cloned_label.id

        await self.session.flush()
        commit_id_map = await self._fork_copy_commits(
            source_project_id=source_project_id,
            target_project_id=forked_project.id,
        )
        annotation_id_map = await self._fork_copy_annotations(
            source_project_id=source_project_id,
            target_project_id=forked_project.id,
            label_id_map=label_id_map,
        )

        source_camap_rows = await self.session.exec(
            select(CommitAnnotationMap).where(CommitAnnotationMap.project_id == source_project_id)
        )
        for source_camap in source_camap_rows.all():
            mapped_commit_id = commit_id_map.get(source_camap.commit_id)
            mapped_annotation_id = annotation_id_map.get(source_camap.annotation_id)
            if not mapped_commit_id:
                raise BadRequestAppException(f"Commit mapping missing for commit {source_camap.commit_id}")
            if not mapped_annotation_id:
                raise BadRequestAppException(
                    f"Annotation mapping missing for annotation {source_camap.annotation_id}"
                )
            self.session.add(CommitAnnotationMap(
                commit_id=mapped_commit_id,
                sample_id=source_camap.sample_id,
                annotation_id=mapped_annotation_id,
                project_id=forked_project.id,
            ))

        source_sample_state_rows = await self.session.exec(
            select(CommitSampleState).where(CommitSampleState.project_id == source_project_id)
        )
        for source_sample_state in source_sample_state_rows.all():
            mapped_commit_id = commit_id_map.get(source_sample_state.commit_id)
            if not mapped_commit_id:
                raise BadRequestAppException(
                    f"Commit mapping missing for commit sample state {source_sample_state.commit_id}"
                )
            self.session.add(CommitSampleState(
                commit_id=mapped_commit_id,
                sample_id=source_sample_state.sample_id,
                project_id=forked_project.id,
                state=source_sample_state.state,
            ))

        source_branch_rows = await self.session.exec(
            select(Branch)
            .where(Branch.project_id == source_project_id)
            .order_by(Branch.created_at.asc())
        )
        source_branches = list(source_branch_rows.all())
        if not source_branches:
            raise BadRequestAppException("Source project has no branch to fork")

        for source_branch in source_branches:
            mapped_head_commit_id = commit_id_map.get(source_branch.head_commit_id)
            if not mapped_head_commit_id:
                raise BadRequestAppException(f"Branch head mapping missing for commit {source_branch.head_commit_id}")
            self.session.add(Branch(
                project_id=forked_project.id,
                name=source_branch.name,
                head_commit_id=mapped_head_commit_id,
                description=source_branch.description,
                is_protected=source_branch.is_protected,
                created_at=source_branch.created_at,
                updated_at=source_branch.updated_at,
            ))

        await self.resource_member_repo.assign_role(
            resource_type=ResourceType.PROJECT,
            resource_id=forked_project.id,
            user_id=user_id,
            role_id=PROJECT_OWNER_ROLE_ID,
        )

        await self.session.flush()
        await self.session.refresh(forked_project)
        return forked_project

    # =========================================================================
    # Dataset Link Management
    # =========================================================================

    @transactional
    async def link_datasets(
            self,
            project_id: uuid.UUID,
            dataset_ids: List[uuid.UUID],
            actor_user_id: uuid.UUID,
    ) -> List[ProjectDataset]:
        """
        Link datasets to a project.

        Args:
            project_id: Project ID
            dataset_ids: List of dataset IDs to link

        Returns:
            List of created ProjectDataset links
        """
        # Verify project exists
        await self.get_by_id_or_raise(project_id)

        # Verify datasets exist
        new_dataset_type = None
        for dataset_id in dataset_ids:
            dataset = await self.dataset_repo.get_by_id(dataset_id)
            if not dataset:
                raise NotFoundAppException(f"Dataset {dataset_id} not found")
            await self._ensure_dataset_link_permission(actor_user_id=actor_user_id, dataset_id=dataset_id)
            if new_dataset_type is None:
                new_dataset_type = dataset.type
            elif dataset.type != new_dataset_type:
                raise BadRequestAppException(
                    "All datasets linked to a project must share the same type"
                )

        # Check for existing links
        existing_ids = await self.repository.get_linked_dataset_ids(project_id)
        new_ids = [did for did in dataset_ids if did not in existing_ids]
        if not new_ids:
            return []

        # Enforce consistent dataset type within project
        if existing_ids:
            for dataset_id in existing_ids:
                existing_dataset = await self.dataset_repo.get_by_id(dataset_id)
                if existing_dataset and existing_dataset.type != new_dataset_type:
                    raise BadRequestAppException(
                        "All datasets linked to a project must share the same type"
                    )

        links = []
        for dataset_id in new_ids:
            link = await self.repository.add_dataset(project_id, dataset_id)
            links.append(link)

        return links

    async def _cascade_cleanup_unlinked_dataset_data(self, project_id: uuid.UUID, dataset_id: uuid.UUID) -> None:
        sample_rows = await self.session.exec(
            select(Sample.id).where(Sample.dataset_id == dataset_id)
        )
        sample_ids = list(sample_rows.all())
        if not sample_ids:
            return

        annotation_rows = await self.session.exec(
            select(Annotation).where(
                Annotation.project_id == project_id,
                Annotation.sample_id.in_(sample_ids),
            )
        )
        annotation_list = list(annotation_rows.all())
        annotation_ids = [row.id for row in annotation_list]

        # Clean commit annotation map by annotation_id first to avoid FK violations.
        if annotation_ids:
            camap_rows = await self.session.exec(
                select(CommitAnnotationMap).where(
                    CommitAnnotationMap.annotation_id.in_(annotation_ids),
                )
            )
            for row in camap_rows:
                await self.session.delete(row)
            # Force delete order: CAMap must be flushed before deleting annotations.
            await self.session.flush()

        draft_rows = await self.session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == project_id,
                AnnotationDraft.sample_id.in_(sample_ids),
            )
        )
        for row in draft_rows:
            await self.session.delete(row)

        for row in annotation_list:
            await self.session.delete(row)

        commit_sample_state_rows = await self.session.exec(
            select(CommitSampleState).where(
                CommitSampleState.project_id == project_id,
                CommitSampleState.sample_id.in_(sample_ids),
            )
        )
        for row in commit_sample_state_rows:
            await self.session.delete(row)

        # Runtime artifacts cleanup (L3 sample-scoped records).
        job_id_rows = await self.session.exec(
            select(Job.id).where(Job.project_id == project_id)
        )
        job_ids = list(job_id_rows.all())
        if job_ids:
            metric_rows = await self.session.exec(
                select(JobSampleMetric).where(
                    JobSampleMetric.job_id.in_(job_ids),
                    JobSampleMetric.sample_id.in_(sample_ids),
                )
            )
            for row in metric_rows:
                await self.session.delete(row)

            task_id_rows = await self.session.exec(
                select(JobTask.id).where(JobTask.job_id.in_(job_ids))
            )
            task_ids = list(task_id_rows.all())
            if task_ids:
                candidate_rows = await self.session.exec(
                    select(TaskCandidateItem).where(
                        TaskCandidateItem.task_id.in_(task_ids),
                        TaskCandidateItem.sample_id.in_(sample_ids),
                    )
                )
                for row in candidate_rows:
                    await self.session.delete(row)

    @transactional
    async def unlink_datasets(
            self,
            project_id: uuid.UUID,
            dataset_ids: List[uuid.UUID],
            actor_user_id: uuid.UUID,
    ) -> int:
        """
        Unlink datasets from a project.

        Args:
            project_id: Project ID
            dataset_ids: List of dataset IDs to unlink

        Returns:
            Number of datasets unlinked
        """
        await self.get_by_id_or_raise(project_id)

        linked_dataset_ids = set(await self.repository.get_linked_dataset_ids(project_id))
        for dataset_id in dataset_ids:
            if dataset_id in linked_dataset_ids:
                await self._ensure_dataset_link_permission(actor_user_id=actor_user_id, dataset_id=dataset_id)

        count = 0
        for dataset_id in dataset_ids:
            if await self.repository.remove_dataset(project_id, dataset_id):
                await self._cascade_cleanup_unlinked_dataset_data(project_id, dataset_id)
                count += 1

        return count

    async def get_linked_datasets(self, project_id: uuid.UUID) -> List[uuid.UUID]:
        """
        Get all dataset IDs linked to a project.

        Args:
            project_id: Project ID

        Returns:
            List of dataset IDs
        """
        await self.get_by_id_or_raise(project_id)
        return await self.repository.get_linked_dataset_ids(project_id)

    async def get_linked_dataset_details(self, project_id: uuid.UUID) -> List[Dataset]:
        """Get linked dataset details for a project in project scope."""
        await self.get_by_id_or_raise(project_id)
        return await self.repository.get_linked_datasets(project_id)

    @staticmethod
    def _empty_project_sample_page(limit: int) -> ProjectSamplePage:
        return ProjectSamplePage(
            samples=[],
            total=0,
            offset=0,
            limit=limit,
            annotation_counts={},
            drafts_by_sample=set(),
            review_states={},
        )

    def _build_project_sample_statement(
            self,
            *,
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            current_user_id: uuid.UUID,
            branch_name: str,
            q: str | None,
            status: str,
            sort_by: str,
            sort_order: str,
            head_commit_id: uuid.UUID | None,
    ):
        statement = select(Sample).where(Sample.dataset_id == dataset_id)
        if q:
            pattern = f"%{q}%"
            statement = statement.where(
                or_(
                    Sample.name.ilike(pattern),
                    Sample.remark.ilike(pattern),
                )
            )

        labeled_subq = select(CommitSampleState.sample_id).where(
            CommitSampleState.commit_id == head_commit_id,
            CommitSampleState.state.in_(
                (
                    CommitSampleReviewState.LABELED,
                    CommitSampleReviewState.EMPTY_CONFIRMED,
                )
            ),
        ).distinct()
        if status == "labeled":
            statement = statement.where(Sample.id.in_(labeled_subq))
        elif status == "unlabeled":
            statement = statement.where(~Sample.id.in_(labeled_subq))
        elif status == "draft":
            draft_subq = select(AnnotationDraft.sample_id).where(
                AnnotationDraft.project_id == project_id,
                AnnotationDraft.user_id == current_user_id,
                AnnotationDraft.branch_name == branch_name,
            ).distinct()
            statement = statement.where(Sample.id.in_(draft_subq))

        sort_map = {
            "name": Sample.name,
            "createdAt": Sample.created_at,
            "updatedAt": Sample.updated_at,
            "created_at": Sample.created_at,
            "updated_at": Sample.updated_at,
        }
        sort_column = sort_map.get(sort_by, Sample.created_at)
        order_clause = asc(sort_column) if sort_order == "asc" else desc(sort_column)
        return statement.order_by(order_clause)

    async def _query_project_samples_page_data(
            self,
            *,
            statement,
            page: int,
            limit: int,
    ) -> tuple[list[Sample], int, Pagination]:
        pagination = Pagination.from_page(page=page, limit=limit)
        count_stmt = select(func.count()).select_from(statement.subquery())
        total_result = await self.session.exec(count_stmt)
        total = total_result.one() or 0
        if isinstance(total, (list, tuple)):
            total = total[0]

        rows = await self.session.exec(
            statement.offset(pagination.offset).limit(pagination.limit)
        )
        return list(rows.all()), int(total), pagination

    async def _query_project_sample_annotation_counts(
            self,
            *,
            sample_ids: list[uuid.UUID],
            head_commit_id: uuid.UUID | None,
    ) -> dict[uuid.UUID, int]:
        annotation_counts: dict[uuid.UUID, int] = {}
        if not sample_ids or not head_commit_id:
            return annotation_counts
        count_statement = (
            select(
                CommitAnnotationMap.sample_id,
                func.count(CommitAnnotationMap.annotation_id),
            )
            .where(
                CommitAnnotationMap.commit_id == head_commit_id,
                CommitAnnotationMap.sample_id.in_(sample_ids),
            )
            .group_by(CommitAnnotationMap.sample_id)
        )
        count_result = await self.session.exec(count_statement)
        for sample_id_item, count in count_result.all():
            annotation_counts[sample_id_item] = count
        return annotation_counts

    async def _query_project_sample_drafts(
            self,
            *,
            project_id: uuid.UUID,
            current_user_id: uuid.UUID,
            branch_name: str,
            sample_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        if not sample_ids:
            return set()
        draft_statement = select(AnnotationDraft.sample_id).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == current_user_id,
            AnnotationDraft.branch_name == branch_name,
            AnnotationDraft.sample_id.in_(sample_ids),
        )
        draft_result = await self.session.exec(draft_statement)
        return {
            row[0] if isinstance(row, (list, tuple)) else row
            for row in draft_result.all()
        }

    async def _query_project_sample_review_states(
            self,
            *,
            sample_ids: list[uuid.UUID],
            head_commit_id: uuid.UUID | None,
    ) -> dict[uuid.UUID, CommitSampleReviewState]:
        if not sample_ids or not head_commit_id:
            return {}
        statement = select(
            CommitSampleState.sample_id,
            CommitSampleState.state,
        ).where(
            CommitSampleState.commit_id == head_commit_id,
            CommitSampleState.sample_id.in_(sample_ids),
        )
        result = await self.session.exec(statement)
        review_states: dict[uuid.UUID, CommitSampleReviewState] = {}
        for sample_id_item, state in result.all():
            review_states[sample_id_item] = state
        return review_states

    async def list_project_samples_page(
            self,
            *,
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            current_user_id: uuid.UUID,
            branch_name: str,
            q: str | None,
            status: str,
            sort_by: str,
            sort_order: str,
            page: int,
            limit: int,
    ) -> ProjectSamplePage:
        dataset_ids = await self.get_linked_datasets(project_id)
        if dataset_id not in dataset_ids:
            return self._empty_project_sample_page(limit)

        branch_repo = BranchRepository(self.session)
        branch = await branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            return self._empty_project_sample_page(limit)
        head_commit_id = branch.head_commit_id

        statement = self._build_project_sample_statement(
            project_id=project_id,
            dataset_id=dataset_id,
            current_user_id=current_user_id,
            branch_name=branch_name,
            q=q,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            head_commit_id=head_commit_id,
        )
        samples, total, pagination = await self._query_project_samples_page_data(
            statement=statement,
            page=page,
            limit=limit,
        )
        sample_ids = [sample.id for sample in samples]
        annotation_counts = await self._query_project_sample_annotation_counts(
            sample_ids=sample_ids,
            head_commit_id=head_commit_id,
        )
        drafts_by_sample = await self._query_project_sample_drafts(
            project_id=project_id,
            current_user_id=current_user_id,
            branch_name=branch_name,
            sample_ids=sample_ids,
        )
        review_states = await self._query_project_sample_review_states(
            sample_ids=sample_ids,
            head_commit_id=head_commit_id,
        )

        return ProjectSamplePage(
            samples=samples,
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
            annotation_counts=annotation_counts,
            drafts_by_sample=drafts_by_sample,
            review_states=review_states,
        )

    # =========================================================================
    # Project Member Management (similar to DatasetService)
    # =========================================================================

    async def get_project_members(self, project_id: uuid.UUID) -> List[ResourceMemberRead]:
        """
        Get all members of a project with user and role information.

        Args:
            project_id: Project ID

        Returns:
            List of ResourceMemberRead objects
        """
        await self.get_by_id_or_raise(project_id)

        result = await self.resource_member_repo.list(
            filters=[
                ResourceMember.resource_type == ResourceType.PROJECT,
                ResourceMember.resource_id == str(project_id)
            ],
            joinedloads=[ResourceMember.user, ResourceMember.role]
        )

        members = [ResourceMemberRead.model_validate(i) for i in result]
        user_service = UserService(self.session)
        for member in members:
            member.user_avatar_url = await user_service.resolve_avatar_url(member.user_avatar_url)
        return members

    @transactional
    async def add_project_member(
            self,
            project_id: uuid.UUID,
            member_data: ResourceMemberCreateRequest
    ) -> ResourceMember:
        """
        Add a member to a project.

        Args:
            project_id: Project ID
            member_data: User ID and role ID to assign

        Returns:
            Created ResourceMember
        """
        await self.get_by_id_or_raise(project_id)

        # Prevent assigning supremo role to new members
        if await self._is_supremo_role(member_data.role_id):
            raise BadRequestAppException(
                "Cannot assign supremo role to members. "
                "Supremo is determined by project creator."
            )

        # Check if member already exists
        from saki_api.repositories.access.resource_member import ResourceMemberRepository
        repo = ResourceMemberRepository(self.session)
        existing = await repo.get_by_user_and_resource(
            member_data.user_id,
            ResourceType.PROJECT,
            str(project_id)
        )
        if existing:
            raise DataAlreadyExistsAppException("User is already a member of this project")

        # Create member
        new_member = ResourceMember(
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
            user_id=member_data.user_id,
            role_id=member_data.role_id,
        )
        created = await self.resource_member_repo.create(new_member.model_dump())
        return created

    @transactional
    async def update_project_member(
            self,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            member_data: ResourceMemberUpdateRequest,
    ) -> ResourceMember:
        """
        Update a project member's role.

        Args:
            project_id: Project ID
            user_id: User ID whose role is being changed
            member_data: New role ID

        Returns:
            Updated ResourceMember
        """
        # Prevent assigning supremo role
        if await self._is_supremo_role(member_data.role_id):
            raise BadRequestAppException(
                "Cannot assign supremo role to members. "
                "Supremo is determined by project creator."
            )

        # Get existing member
        existing = await self.resource_member_repo.get_by_user_and_resource(
            user_id,
            ResourceType.PROJECT,
            str(project_id)
        )
        if not existing:
            raise NotFoundAppException("Member not found")
        if await self._is_supremo_role(existing.role_id):
            raise BadRequestAppException("Cannot modify project supremo membership")

        # Update member
        updated = await self.resource_member_repo.update(
            existing.id,
            {"role_id": member_data.role_id}
        )
        if updated is None:
            raise BadRequestAppException("Failed to update member")
        return updated

    @transactional
    async def remove_project_member(
            self,
            project_id: uuid.UUID,
            user_id: uuid.UUID,
            current_user_id: uuid.UUID,
    ) -> None:
        """
        Remove a member from a project.

        Args:
            project_id: Project ID
            user_id: User ID to remove
            current_user_id: Current user ID (cannot remove self)
        """
        await self.get_by_id_or_raise(project_id)

        if current_user_id == user_id:
            raise BadRequestAppException("Cannot remove yourself")

        # Get existing member
        existing = await self.resource_member_repo.get_by_user_and_resource(
            user_id,
            ResourceType.PROJECT,
            str(project_id)
        )
        if not existing:
            raise NotFoundAppException("Member not found")
        if await self._is_supremo_role(existing.role_id):
            raise BadRequestAppException("Cannot remove project supremo membership")

        # Delete member
        await self.resource_member_repo.delete(existing.id)

    # =========================================================================
    # Annotation Save Workflow (L2 Core Transaction)
    # =========================================================================

    @staticmethod
    def _normalize_annotation_scalar(value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    @classmethod
    def _normalize_annotation_item(cls, item: dict) -> dict:
        ann_type = item.get("type")
        ann_source = item.get("source")
        return {
            "group_id": cls._normalize_annotation_scalar(item.get("group_id") or item.get("groupId")),
            "lineage_id": cls._normalize_annotation_scalar(item.get("lineage_id") or item.get("lineageId")),
            "label_id": cls._normalize_annotation_scalar(item.get("label_id")),
            "view_role": item.get("view_role") or item.get("viewRole") or "main",
            "type": ann_type.value if hasattr(ann_type, "value") else str(ann_type),
            "source": ann_source.value if hasattr(ann_source, "value") else str(ann_source or "manual"),
            "data": item.get("data") or {},
            "extra": item.get("extra") or {},
            "confidence": float(item.get("confidence") or 1.0),
            "annotator_id": cls._normalize_annotation_scalar(item.get("annotator_id") or item.get("annotatorId")),
        }

    @classmethod
    def _is_same_annotation_item(cls, change_item: dict, existing: Annotation) -> bool:
        change_norm = cls._normalize_annotation_item(change_item)
        existing_norm = cls._normalize_annotation_item({
            "group_id": existing.group_id,
            "lineage_id": existing.lineage_id,
            "label_id": existing.label_id,
            "view_role": existing.view_role,
            "type": existing.type,
            "source": existing.source,
            "data": existing.data,
            "extra": existing.extra,
            "confidence": existing.confidence,
            "annotator_id": existing.annotator_id,
        })
        return json.dumps(change_norm, sort_keys=True) == json.dumps(existing_norm, sort_keys=True)

    def _group_annotation_changes(
            self,
            *,
            annotation_changes: Sequence[dict],
            project_id: uuid.UUID,
            author_id: uuid.UUID,
    ) -> dict[uuid.UUID, list[dict]]:
        draft_by_sample: dict[uuid.UUID, list[dict]] = {}
        for change in annotation_changes:
            normalized = dict(change)
            sample_id_value = normalized.get("sample_id") or normalized.get("sampleId")
            if not sample_id_value:
                raise BadRequestAppException("annotation sample_id is required")
            sample_id = uuid.UUID(str(sample_id_value))
            normalized["sample_id"] = sample_id
            normalized["project_id"] = uuid.UUID(str(normalized.get("project_id") or project_id))
            normalized["annotator_id"] = uuid.UUID(str(normalized.get("annotator_id") or author_id))
            normalized["view_role"] = normalized.get("view_role") or normalized.get("viewRole") or "main"
            normalized["source"] = normalized.get("source") or "manual"
            normalized["id"] = normalized.get("id") or normalized.get("annotation_id")
            normalized["group_id"] = normalized.get("group_id") or normalized.get("groupId")
            normalized["lineage_id"] = normalized.get("lineage_id") or normalized.get("lineageId")
            if not normalized["group_id"]:
                raise BadRequestAppException("annotation group_id is required")
            if not normalized["lineage_id"]:
                raise BadRequestAppException("annotation lineage_id is required")
            draft_by_sample.setdefault(sample_id, []).append(normalized)
        return draft_by_sample

    async def _load_existing_annotations_by_sample(
            self,
            *,
            annotation_repo: AnnotationRepository,
            current_head_id: uuid.UUID | None,
            touched_sample_ids: Set[uuid.UUID],
    ) -> dict[uuid.UUID, list[Annotation]]:
        existing_by_sample: dict[uuid.UUID, list[Annotation]] = {}
        if not current_head_id:
            return existing_by_sample
        for sample_id in touched_sample_ids:
            existing = await annotation_repo.get_by_commit_and_sample(current_head_id, sample_id)
            existing_by_sample[sample_id] = list(existing)
        return existing_by_sample

    def _build_annotations_for_samples(
            self,
            *,
            project_id: uuid.UUID,
            author_id: uuid.UUID,
            draft_by_sample: dict[uuid.UUID, list[dict]],
            existing_by_sample: dict[uuid.UUID, list[Annotation]],
            touched_sample_ids: Set[uuid.UUID],
    ) -> tuple[list[Annotation], list[tuple[uuid.UUID, uuid.UUID]]]:
        new_annotations: list[Annotation] = []
        camap_mappings: list[tuple[uuid.UUID, uuid.UUID]] = []

        for sample_id in touched_sample_ids:
            draft_items = draft_by_sample.get(sample_id, [])
            existing_list = existing_by_sample.get(sample_id, [])
            existing_by_lineage: dict[str, Annotation] = {
                str(ann.lineage_id): ann for ann in existing_list
            }

            for item in draft_items:
                lineage_id = str(item.get("lineage_id"))
                existing_ann = existing_by_lineage.get(lineage_id)
                if existing_ann and self._is_same_annotation_item(item, existing_ann):
                    camap_mappings.append((sample_id, existing_ann.id))
                    continue

                annotation = Annotation(
                    project_id=item.get("project_id") or project_id,
                    sample_id=sample_id,
                    label_id=item.get("label_id"),
                    group_id=item.get("group_id"),
                    lineage_id=item.get("lineage_id"),
                    parent_id=existing_ann.id if existing_ann else None,
                    view_role=item.get("view_role") or "main",
                    type=item.get("type"),
                    source=item.get("source") or "manual",
                    data=item.get("data") or {},
                    extra=item.get("extra") or {},
                    confidence=float(item.get("confidence") or 1.0),
                    annotator_id=item.get("annotator_id") or author_id,
                )
                self.session.add(annotation)
                new_annotations.append(annotation)

        return new_annotations, camap_mappings

    async def _append_new_annotation_mappings(
            self,
            *,
            new_annotations: list[Annotation],
            camap_mappings: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> None:
        await self.session.flush()
        for ann in new_annotations:
            await self.session.refresh(ann)
            camap_mappings.append((ann.sample_id, ann.id))

    async def _create_user_commit(
            self,
            *,
            project_id: uuid.UUID,
            parent_id: uuid.UUID | None,
            commit_message: str,
            author_id: uuid.UUID,
    ) -> Commit:
        new_commit = Commit(
            project_id=project_id,
            parent_id=parent_id,
            message=commit_message,
            author_type=AuthorType.USER,
            author_id=author_id,
            stats={},
            commit_hash="",
        )
        self.session.add(new_commit)
        await self.session.flush()
        await self.session.refresh(new_commit)
        return new_commit

    async def _apply_camap_for_commit(
            self,
            *,
            camap_service: CAMapService,
            project_id: uuid.UUID,
            current_head_id: uuid.UUID | None,
            new_commit: Commit,
            touched_sample_ids: Set[uuid.UUID],
            camap_mappings: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> None:
        if current_head_id:
            await camap_service.copy_commit_state(
                source_commit_id=current_head_id,
                target_commit_id=new_commit.id,
                project_id=project_id,
            )

        for sample_id in touched_sample_ids:
            await camap_service.camap_repo.delete_commit_sample_state(
                commit_id=new_commit.id,
                sample_id=sample_id,
            )

        if camap_mappings:
            await camap_service.camap_repo.set_commit_state(
                commit_id=new_commit.id,
                mappings=camap_mappings,
                project_id=project_id,
            )

        new_commit.stats = await camap_service.get_commit_stats(new_commit.id)
        await self.session.flush()

    async def _apply_sample_review_state_for_commit(
            self,
            *,
            project_id: uuid.UUID,
            current_head_id: uuid.UUID | None,
            new_commit: Commit,
            touched_sample_ids: Set[uuid.UUID],
            camap_mappings: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> None:
        state_repo = CommitSampleStateRepository(self.session)
        if current_head_id:
            await state_repo.copy_commit_state(
                source_commit_id=current_head_id,
                target_commit_id=new_commit.id,
                project_id=project_id,
            )

        touched_with_annotations = {
            sample_id
            for sample_id, _annotation_id in camap_mappings
            if sample_id in touched_sample_ids
        }

        for sample_id in touched_sample_ids:
            await state_repo.delete_commit_sample_state(
                commit_id=new_commit.id,
                sample_id=sample_id,
            )
            state = (
                CommitSampleReviewState.LABELED
                if sample_id in touched_with_annotations
                else CommitSampleReviewState.EMPTY_CONFIRMED
            )
            await state_repo.set_commit_sample_state(
                commit_id=new_commit.id,
                sample_id=sample_id,
                project_id=project_id,
                state=state,
            )

    @transactional
    async def save_annotations(
            self,
            project_id: uuid.UUID,
            branch_name: str,
            annotation_changes: List[dict],
            commit_message: str,
            author_id: uuid.UUID,
            touched_sample_ids: List[uuid.UUID] | None = None,
    ) -> Commit:
        """
        Save annotations and create a new commit.

        This is the core L2 annotation save workflow:
        1. Get current branch and HEAD commit
        2. Diff drafts vs HEAD commit using lineage_id + deep compare
        3. Create new Annotation records for changed items only
        4. Create new Commit (parent_id = current HEAD)
        5. Copy CAMap state and replace touched sample entries
        6. Update branch HEAD to new commit

        Args:
            project_id: Project ID
            branch_name: Branch name (e.g., "master")
            annotation_changes: Full snapshot list of annotation data dicts
            commit_message: Commit message
            author_id: User ID creating the commit

        Returns:
            Created Commit
        """
        branch_repo = BranchRepository(self.session)
        branch = await branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            raise NotFoundAppException(f"Branch '{branch_name}' not found in project")

        current_head_id = branch.head_commit_id
        annotation_repo = AnnotationRepository(self.session)
        camap_service = CAMapService(self.session)
        draft_by_sample = self._group_annotation_changes(
            annotation_changes=annotation_changes,
            project_id=project_id,
            author_id=author_id,
        )
        touched_sample_set = set(touched_sample_ids or draft_by_sample.keys())

        existing_by_sample = await self._load_existing_annotations_by_sample(
            annotation_repo=annotation_repo,
            current_head_id=current_head_id,
            touched_sample_ids=touched_sample_set,
        )
        new_annotations, camap_mappings = self._build_annotations_for_samples(
            project_id=project_id,
            author_id=author_id,
            draft_by_sample=draft_by_sample,
            existing_by_sample=existing_by_sample,
            touched_sample_ids=touched_sample_set,
        )
        await self._append_new_annotation_mappings(
            new_annotations=new_annotations,
            camap_mappings=camap_mappings,
        )

        new_commit = await self._create_user_commit(
            project_id=project_id,
            parent_id=current_head_id,
            commit_message=commit_message,
            author_id=author_id,
        )
        await self._apply_camap_for_commit(
            camap_service=camap_service,
            project_id=project_id,
            current_head_id=current_head_id,
            new_commit=new_commit,
            touched_sample_ids=touched_sample_set,
            camap_mappings=camap_mappings,
        )
        await self._apply_sample_review_state_for_commit(
            project_id=project_id,
            current_head_id=current_head_id,
            new_commit=new_commit,
            touched_sample_ids=touched_sample_set,
            camap_mappings=camap_mappings,
        )
        await refresh_commit_hash(self.session, new_commit)
        await branch_repo.update_head(branch.id, new_commit.id)

        await self.session.refresh(new_commit)
        return new_commit
