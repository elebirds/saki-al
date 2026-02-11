"""
Project Service - Business logic for Project operations.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, List, Sequence, Set

from sqlalchemy import asc, desc, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import DataAlreadyExistsAppException, NotFoundAppException, BadRequestAppException
from saki_api.core.rbac.presets import PROJECT_OWNER_ROLE_ID
from saki_api.db.transaction import transactional
from saki_api.models import ResourceType
from saki_api.models.enums import AuthorType
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.annotation_draft import AnnotationDraft
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.project import Project, ProjectDataset
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_task import JobTask
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.task_candidate_item import TaskCandidateItem
from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.repositories.annotation import AnnotationRepository
from saki_api.repositories.branch import BranchRepository
from saki_api.repositories.dataset import DatasetRepository
from saki_api.repositories.label import LabelRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.repositories.query import Pagination
from saki_api.repositories.resource_member import ResourceMemberRepository
from saki_api.schemas.project import ProjectCreate, ProjectUpdate
from saki_api.schemas.resource_member import ResourceMemberCreateRequest, ResourceMemberRead, \
    ResourceMemberUpdateRequest
from saki_api.services.base import BaseService
from saki_api.services.camap import CAMapService
from saki_api.services.user import UserService


@dataclass
class ProjectSamplePage:
    samples: list[Sample]
    total: int
    offset: int
    limit: int
    annotation_counts: dict[uuid.UUID, int]
    drafts_by_sample: set[uuid.UUID]


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
        )
        self.session.add(initial_commit)
        await self.session.flush()
        await self.session.refresh(initial_commit)

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
        }

    # =========================================================================
    # Dataset Link Management
    # =========================================================================

    @transactional
    async def link_datasets(self, project_id: uuid.UUID, dataset_ids: List[uuid.UUID]) -> List[ProjectDataset]:
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

        batch_item_rows = await self.session.exec(
            select(AnnotationBatchItem)
            .join(AnnotationBatch, AnnotationBatch.id == AnnotationBatchItem.batch_id)
            .where(
                AnnotationBatch.project_id == project_id,
                AnnotationBatchItem.sample_id.in_(sample_ids),
            )
        )
        affected_batch_ids: set[uuid.UUID] = set()
        for row in batch_item_rows:
            affected_batch_ids.add(row.batch_id)
            await self.session.delete(row)

        # Recompute batch counters after item cleanup.
        for batch_id in affected_batch_ids:
            total_result = await self.session.exec(
                select(func.count()).select_from(
                    select(AnnotationBatchItem).where(AnnotationBatchItem.batch_id == batch_id).subquery()
                )
            )
            total_count = total_result.one() or 0
            annotated_result = await self.session.exec(
                select(func.count()).select_from(
                    select(AnnotationBatchItem).where(
                        AnnotationBatchItem.batch_id == batch_id,
                        AnnotationBatchItem.is_annotated == True,
                    ).subquery()
                )
            )
            annotated_count = annotated_result.one() or 0
            batch = await self.session.get(AnnotationBatch, batch_id)
            if batch:
                batch.total_count = int(total_count)
                batch.annotated_count = int(annotated_count)
                self.session.add(batch)

    @transactional
    async def unlink_datasets(self, project_id: uuid.UUID, dataset_ids: List[uuid.UUID]) -> int:
        """
        Unlink datasets from a project.

        Args:
            project_id: Project ID
            dataset_ids: List of dataset IDs to unlink

        Returns:
            Number of datasets unlinked
        """
        await self.get_by_id_or_raise(project_id)

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

    @staticmethod
    def _empty_project_sample_page(limit: int) -> ProjectSamplePage:
        return ProjectSamplePage(
            samples=[],
            total=0,
            offset=0,
            limit=limit,
            annotation_counts={},
            drafts_by_sample=set(),
        )

    def _build_project_sample_statement(
            self,
            *,
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            current_user_id: uuid.UUID,
            branch_name: str,
            q: str | None,
            batch_id: uuid.UUID | None,
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

        if batch_id:
            batch_stmt = (
                select(AnnotationBatchItem.sample_id)
                .join(AnnotationBatch, AnnotationBatch.id == AnnotationBatchItem.batch_id)
                .where(
                    AnnotationBatchItem.batch_id == batch_id,
                    AnnotationBatch.project_id == project_id,
                )
            )
            statement = statement.where(Sample.id.in_(batch_stmt))

        labeled_subq = select(CommitAnnotationMap.sample_id).where(
            CommitAnnotationMap.commit_id == head_commit_id
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

    async def list_project_samples_page(
            self,
            *,
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            current_user_id: uuid.UUID,
            branch_name: str,
            q: str | None,
            batch_id: uuid.UUID | None,
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
            batch_id=batch_id,
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

        return ProjectSamplePage(
            samples=samples,
            total=total,
            offset=pagination.offset,
            limit=pagination.limit,
            annotation_counts=annotation_counts,
            drafts_by_sample=drafts_by_sample,
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

        # Prevent assigning owner role to new members
        if member_data.role_id == PROJECT_OWNER_ROLE_ID:
            raise BadRequestAppException(
                "Cannot assign owner role to members. "
                "Owner is determined by project creator."
            )

        # Check if member already exists
        from saki_api.repositories.resource_member import ResourceMemberRepository
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
        # TODO: Add owner_id field to Project model
        # For now, skip owner check

        # Prevent assigning owner role
        if member_data.role_id == PROJECT_OWNER_ROLE_ID:
            raise BadRequestAppException(
                "Cannot assign owner role to members. "
                "Owner is determined by project creator."
            )

        # Get existing member
        existing = await self.resource_member_repo.get_by_user_and_resource(
            user_id,
            ResourceType.PROJECT,
            str(project_id)
        )
        if not existing:
            raise NotFoundAppException("Member not found")

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
        await branch_repo.update_head(branch.id, new_commit.id)

        await self.session.refresh(new_commit)
        return new_commit
