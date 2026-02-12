"""
Branch Repository - Data access layer for Branch operations.
"""

import uuid
from typing import List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.project.branch import Branch
from saki_api.repositories.base import BaseRepository


class BranchRepository(BaseRepository[Branch]):
    """Repository for Branch data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Branch, session)

    async def get_by_project(self, project_id: uuid.UUID) -> List[Branch]:
        """
        Get all branches for a project.

        Args:
            project_id: Project ID

        Returns:
            List of branches
        """
        return await self.list(
            filters=[Branch.project_id == project_id],
            order_by=[Branch.created_at]
        )

    async def get_master_branch(self, project_id: uuid.UUID) -> Optional[Branch]:
        """
        Get the master branch for a project.

        Args:
            project_id: Project ID

        Returns:
            Master branch if found, None otherwise
        """
        return await self.get_one(
            filters=[Branch.project_id == project_id, Branch.name == "master"]
        )

    async def get_by_name(self, project_id: uuid.UUID, name: str) -> Optional[Branch]:
        """
        Get a branch by name within a project.

        Args:
            project_id: Project ID
            name: Branch name

        Returns:
            Branch if found, None otherwise
        """
        return await self.get_one(
            filters=[Branch.project_id == project_id, Branch.name == name]
        )

    async def get_with_head(self, branch_id: uuid.UUID) -> Optional[Branch]:
        """
        Get a branch with HEAD commit preloaded.

        Args:
            branch_id: Branch ID

        Returns:
            Branch with head_commit relationship loaded
        """
        return await self.get_one(
            filters=[Branch.id == branch_id],
            joinedloads=[Branch.head_commit]
        )

    async def get_by_project_with_head(self, project_id: uuid.UUID) -> List[Branch]:
        """
        Get all branches for a project with HEAD commits preloaded.

        Args:
            project_id: Project ID

        Returns:
            List of branches with head_commit loaded
        """
        return await self.list(
            filters=[Branch.project_id == project_id],
            joinedloads=[Branch.head_commit],
            order_by=[Branch.created_at]
        )

    async def update_head(self, branch_id: uuid.UUID, commit_id: uuid.UUID) -> Optional[Branch]:
        """
        Update the HEAD pointer of a branch.

        Args:
            branch_id: Branch ID
            commit_id: New HEAD commit ID

        Returns:
            Updated branch if found, None otherwise
        """
        branch = await self.get_by_id(branch_id)
        if not branch:
            return None

        branch.head_commit_id = commit_id
        self.session.add(branch)
        await self.session.flush()
        await self.session.refresh(branch)
        return branch

    async def name_exists(self, project_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None) -> bool:
        """
        Check if a branch name exists in a project.

        Args:
            project_id: Project ID
            name: Branch name
            exclude_id: Optional branch ID to exclude from check (for updates)

        Returns:
            True if name exists, False otherwise
        """
        filters = [Branch.project_id == project_id, Branch.name == name]
        if exclude_id:
            filters.append(Branch.id != exclude_id)
        return await self.exists(filters)

    async def find_by_head_commit(self, commit_id: uuid.UUID) -> List[Branch]:
        """
        Find all branches pointing to a specific commit.

        Args:
            commit_id: Commit ID

        Returns:
            List of branches with this commit as HEAD
        """
        return await self.list(
            filters=[Branch.head_commit_id == commit_id]
        )
