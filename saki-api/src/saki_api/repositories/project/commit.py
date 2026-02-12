"""
Commit Repository - Data access layer for Commit operations.
"""

import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.project.commit import Commit
from saki_api.repositories.base import BaseRepository


class CommitRepository(BaseRepository[Commit]):
    """Repository for Commit data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Commit, session)

    async def get_by_project(self, project_id: uuid.UUID) -> List[Commit]:
        """
        Get all commits for a project, ordered by created_at DESC.

        Args:
            project_id: Project ID

        Returns:
            List of commits, newest first
        """
        return await self.list(
            filters=[Commit.project_id == project_id],
            order_by=[Commit.created_at.desc()]
        )

    async def get_history(self, commit_id: uuid.UUID, depth: int = 100) -> List[Commit]:
        """
        Get commit history by following parent_id chain.

        Args:
            commit_id: Starting commit ID
            depth: Maximum depth to traverse

        Returns:
            List of commits from oldest to newest
        """
        history = []
        current_id = commit_id
        count = 0

        while current_id and count < depth:
            commit = await self.get_by_id(current_id)
            if not commit:
                break
            history.insert(0, commit)  # Prepend to get chronological order
            current_id = commit.parent_id
            count += 1

        return history

    async def get_branch_head(self, branch_id: uuid.UUID) -> Optional[Commit]:
        """
        Get the HEAD commit of a branch.

        Args:
            branch_id: Branch ID

        Returns:
            Commit if found, None otherwise
        """
        from saki_api.models.project.branch import Branch

        statement = (
            select(Commit)
            .join(Branch, Branch.head_commit_id == Commit.id)
            .where(Branch.id == branch_id)
        )
        result = await self.session.exec(statement)
        return result.first()

    async def find_root_commit(self, project_id: uuid.UUID) -> Optional[Commit]:
        """
        Find the initial commit (parent_id is NULL) for a project.

        Args:
            project_id: Project ID

        Returns:
            Root commit if found, None otherwise
        """
        return await self.get_one(
            filters=[Commit.project_id == project_id, Commit.parent_id.is_(None)]
        )

    async def get_by_parent(self, parent_id: uuid.UUID) -> List[Commit]:
        """
        Get all commits that have a specific parent.

        Args:
            parent_id: Parent commit ID

        Returns:
            List of child commits
        """
        return await self.list(
            filters=[Commit.parent_id == parent_id],
            order_by=[Commit.created_at]
        )

    async def get_with_parent(self, commit_id: uuid.UUID) -> Optional[Commit]:
        """
        Get a commit with its parent preloaded.

        Args:
            commit_id: Commit ID

        Returns:
            Commit with parent relationship loaded
        """
        # Note: self relationship loading is more complex
        # For now, we'll do a simple get
        return await self.get_by_id(commit_id)

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """
        Count commits for a project.

        Args:
            project_id: Project ID

        Returns:
            Number of commits
        """
        from sqlalchemy import func

        statement = select(func.count()).select_from(
            select(Commit).where(Commit.project_id == project_id).subquery()
        )
        result = await self.session.exec(statement)
        return result.one() or 0
