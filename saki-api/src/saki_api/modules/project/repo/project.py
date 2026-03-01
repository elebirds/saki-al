"""
Project Repository - Data access layer for Project operations.
"""

import uuid
from typing import List

from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import Pagination
from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.access.domain.rbac import ResourceType, Permissions
from saki_api.modules.storage.domain.dataset import Dataset


class ProjectRepository(BaseRepository[Project]):
    """Repository for Project data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Project, session)

    async def get_with_datasets(self, project_id: uuid.UUID) -> Project | None:
        """
        Get project with datasets preloaded.

        Args:
            project_id: Project ID

        Returns:
            Project with dataset_links loaded, or None
        """
        return await self.get_one(
            filters=[Project.id == project_id],
            joinedloads=[Project.dataset_links]
        )

    async def get_with_relations(self, project_id: uuid.UUID) -> Project | None:
        """
        Get project with all L2 relations preloaded.

        Args:
            project_id: Project ID

        Returns:
            Project with branches, commits, labels, dataset_links loaded
        """
        return await self.get_one(
            filters=[Project.id == project_id],
            joinedloads=[
                Project.dataset_links,
                Project.branches,
                Project.commits,
                Project.labels,
            ]
        )

    async def get_by_dataset_id(self, dataset_id: uuid.UUID) -> List[Project]:
        """
        Get all projects that include this dataset.

        Args:
            dataset_id: Dataset ID

        Returns:
            List of projects
        """
        statement = (
            select(Project)
            .join(ProjectDataset)
            .where(ProjectDataset.dataset_id == dataset_id)
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def add_dataset(self, project_id: uuid.UUID, dataset_id: uuid.UUID) -> ProjectDataset:
        """
        Add a dataset to a project.

        Args:
            project_id: Project ID
            dataset_id: Dataset ID

        Returns:
            Created ProjectDataset link
        """
        link = ProjectDataset(project_id=project_id, dataset_id=dataset_id)
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def remove_dataset(self, project_id: uuid.UUID, dataset_id: uuid.UUID) -> bool:
        """
        Remove a dataset from a project.

        Args:
            project_id: Project ID
            dataset_id: Dataset ID

        Returns:
            True if removed, False if link didn't exist
        """
        statement = select(ProjectDataset).where(
            ProjectDataset.project_id == project_id,
            ProjectDataset.dataset_id == dataset_id
        )
        result = await self.session.exec(statement)
        link = result.first()
        if not link:
            return False
        await self.session.delete(link)
        await self.session.flush()
        return True

    async def list_in_permission_paginated(
            self, user_id: uuid.UUID, pagination: Pagination
    ) -> PaginationResponse[Project]:
        """
        List projects accessible to user with pagination.

        Args:
            user_id: User ID
            pagination: Pagination parameters

        Returns:
            Paginated list of accessible projects
        """
        checker = PermissionChecker(self.session)
        base_query = self.list_statement()
        filtered_stmt = await checker.filter_accessible_resources(
            user_id=user_id,
            resource_type=ResourceType.PROJECT,
            required_permission=Permissions.PROJECT_READ,
            base_query=base_query,
            resource_model=Project,
        )

        items_result = await self.session.exec(
            filtered_stmt.offset(pagination.offset).limit(pagination.limit)
        )
        items = list(items_result.all())

        total = await self.session.scalar(
            select(func.count()).select_from(filtered_stmt.subquery())
        ) or 0

        return PaginationResponse.from_items(items, total, pagination.offset, pagination.limit)

    async def list_in_permission(self, user_id: uuid.UUID) -> List[Project]:
        """List projects accessible to user without pagination."""
        checker = PermissionChecker(self.session)
        filtered_stmt = await checker.filter_accessible_resources(
            user_id=user_id,
            resource_type=ResourceType.PROJECT,
            required_permission=Permissions.PROJECT_READ,
            base_query=self.list_statement(),
            resource_model=Project,
        )
        result = await self.session.exec(filtered_stmt)
        return list(result.all())

    async def get_linked_dataset_ids(self, project_id: uuid.UUID) -> List[uuid.UUID]:
        """
        Get all dataset IDs linked to a project.

        Args:
            project_id: Project ID

        Returns:
            List of dataset IDs
        """
        statement = select(ProjectDataset.dataset_id).where(
            ProjectDataset.project_id == project_id
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_linked_datasets(self, project_id: uuid.UUID) -> List[Dataset]:
        """Get linked datasets for a project."""
        statement = (
            select(Dataset)
            .join(ProjectDataset, ProjectDataset.dataset_id == Dataset.id)
            .where(ProjectDataset.project_id == project_id)
            .order_by(Dataset.created_at.desc())
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def count_datasets(self, project_id: uuid.UUID) -> int:
        """Count datasets linked to a project."""
        statement = select(func.count()).select_from(
            select(ProjectDataset).where(ProjectDataset.project_id == project_id).subquery()
        )
        return await self.session.scalar(statement) or 0

    async def count_labels(self, project_id: uuid.UUID) -> int:
        """Count labels in a project."""
        from saki_api.modules.project.domain.label import Label
        statement = select(func.count()).select_from(
            select(Label).where(Label.project_id == project_id).subquery()
        )
        return await self.session.scalar(statement) or 0

    async def count_branches(self, project_id: uuid.UUID) -> int:
        """Count branches in a project."""
        from saki_api.modules.project.domain.branch import Branch
        statement = select(func.count()).select_from(
            select(Branch).where(Branch.project_id == project_id).subquery()
        )
        return await self.session.scalar(statement) or 0

    async def count_commits(self, project_id: uuid.UUID) -> int:
        """Count commits in a project."""
        from saki_api.modules.project.domain.commit import Commit
        statement = select(func.count()).select_from(
            select(Commit).where(Commit.project_id == project_id).subquery()
        )
        return await self.session.scalar(statement) or 0

    async def count_annotations(self, project_id: uuid.UUID) -> int:
        """Count annotations in a project."""
        from saki_api.modules.annotation.domain.annotation import Annotation
        statement = select(func.count()).select_from(
            select(Annotation).where(Annotation.project_id == project_id).subquery()
        )
        return await self.session.scalar(statement) or 0

    async def count_forks(self, project_id: uuid.UUID) -> int:
        """
        Count how many projects are forked from the given project.

        Fork relation is stored in project.config.fork_meta.source_project_id.
        """
        result = await self.session.exec(
            select(Project.config).where(Project.id != project_id)
        )
        target = str(project_id)
        count = 0
        for config in result.all():
            if not isinstance(config, dict):
                continue
            fork_meta = config.get("fork_meta")
            if not isinstance(fork_meta, dict):
                continue
            source_project_id = str(fork_meta.get("source_project_id") or "")
            if source_project_id == target:
                count += 1
        return count
