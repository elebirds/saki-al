"""
Project Service - Business logic for Project operations.
"""

import logging
import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import DataAlreadyExistsAppException, NotFoundAppException, BadRequestAppException
from saki_api.core.rbac.presets import DATASET_OWNER_ROLE_ID
from saki_api.db.transaction import transactional
from saki_api.models import ResourceType
from saki_api.models.enums import AuthorType
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.project import Project, ProjectDataset
from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.repositories.dataset import DatasetRepository
from saki_api.repositories.label import LabelRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.repositories.resource_member import ResourceMemberRepository
from saki_api.schemas.project import ProjectCreate, ProjectUpdate
from saki_api.schemas.resource_member import ResourceMemberCreateRequest, ResourceMemberRead, \
    ResourceMemberUpdateRequest
from saki_api.services.base import BaseService

logger = logging.getLogger(__name__)

# TODO: Define PROJECT_OWNER_ROLE_ID in presets
PROJECT_OWNER_ROLE_ID = DATASET_OWNER_ROLE_ID  # Use same for now


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

        return [ResourceMemberRead.model_validate(i) for i in result]

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
        2. Create new Annotation records (with parent_id if modifying)
        3. Create new Commit (parent_id = current HEAD)
        4. Create CAMap entries for new annotations
        5. Update branch HEAD to new commit

        Args:
            project_id: Project ID
            branch_name: Branch name (e.g., "master")
            annotation_changes: List of annotation data dicts
            commit_message: Commit message
            author_id: User ID creating the commit

        Returns:
            Created Commit
        """
        from saki_api.repositories.annotation import AnnotationRepository
        from saki_api.repositories.branch import BranchRepository
        from saki_api.repositories.commit import CommitRepository
        from saki_api.services.camap import CAMapService
        from saki_api.models.l2.annotation import Annotation
        from saki_api.models.l2.commit import Commit

        # 1. Get current branch
        branch_repo = BranchRepository(self.session)
        branch = await branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            raise NotFoundAppException(f"Branch '{branch_name}' not found in project")

        # 2. Get current HEAD commit
        commit_repo = CommitRepository(self.session)
        current_head_id = branch.head_commit_id

        # 3. Create new Annotation records
        annotation_repo = AnnotationRepository(self.session)
        new_annotations = []

        for change in annotation_changes:
            # Verify parent_id exists if provided
            if change.get("parent_id"):
                parent = await annotation_repo.get_by_id(change["parent_id"])
                if not parent:
                    raise NotFoundAppException(f"Parent annotation {change['parent_id']} not found")

            annotation = Annotation(**change)
            self.session.add(annotation)
            new_annotations.append(annotation)

        await self.session.flush()

        # Refresh to get IDs
        for ann in new_annotations:
            await self.session.refresh(ann)

        # 4. Create new Commit
        new_commit = Commit(
            project_id=project_id,
            parent_id=current_head_id,
            message=commit_message,
            author_type=AuthorType.USER,
            author_id=author_id,
            stats={
                "annotation_count": len(new_annotations),
                "sample_count": len(set(a.sample_id for a in new_annotations)),
            },
        )
        self.session.add(new_commit)
        await self.session.flush()
        await self.session.refresh(new_commit)

        # 5. Create CAMap entries
        camap_service = CAMapService(self.session)
        if current_head_id:
            await camap_service.copy_commit_state(
                source_commit_id=current_head_id,
                target_commit_id=new_commit.id,
                project_id=project_id,
            )

        # Replace CAMap entries for samples touched by this commit
        touched_sample_ids = set(touched_sample_ids or [a.sample_id for a in new_annotations])
        for sample_id in touched_sample_ids:
            await camap_service.camap_repo.delete_commit_sample_state(
                commit_id=new_commit.id,
                sample_id=sample_id,
            )

        await camap_service.create_commit_state(
            commit_id=new_commit.id,
            annotations=new_annotations,
            project_id=project_id,
        )

        # 6. Update branch HEAD
        await branch_repo.update_head(branch.id, new_commit.id)

        await self.session.refresh(new_commit)
        return new_commit
