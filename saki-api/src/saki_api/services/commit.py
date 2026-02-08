"""
Commit Service - Business logic for Commit operations.
"""

from loguru import logger
import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException, BadRequestAppException
from saki_api.db.transaction import transactional
from saki_api.models.l2.commit import Commit
from saki_api.repositories.branch import BranchRepository
from saki_api.repositories.commit import CommitRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.schemas.commit import CommitCreate, CommitHistoryItem, CommitTree, CommitDiff
from saki_api.services.base import BaseService



class CommitService(BaseService[Commit, CommitRepository, CommitCreate, dict]):
    """
    Service for managing Commits.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Commit, CommitRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.branch_repo = BranchRepository(session)

    @transactional
    async def create_commit(
            self,
            project_id: uuid.UUID,
            message: str,
            parent_id: uuid.UUID | None = None,
            author_type: str = "USER",
            author_id: uuid.UUID | None = None,
            stats: dict | None = None,
    ) -> Commit:
        """
        Create a new commit.

        Args:
            project_id: Project ID
            message: Commit message
            parent_id: Parent commit ID (None for root commit)
            author_type: Type of author (USER, MODEL, SYSTEM)
            author_id: ID of the author
            stats: Commit statistics

        Returns:
            Created commit

        Raises:
            NotFoundAppException: If project or parent commit not found
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        # Verify parent commit exists if provided
        if parent_id:
            parent = await self.get_by_id(parent_id)
            if not parent:
                raise NotFoundAppException(f"Parent commit {parent_id} not found")
            if parent.project_id != project_id:
                raise BadRequestAppException("Parent commit must belong to the same project")

        commit_data = {
            "project_id": project_id,
            "message": message,
            "parent_id": parent_id,
            "author_type": author_type,
            "author_id": author_id,
            "stats": stats or {},
        }

        return await self.create(commit_data)

    async def get_history(self, commit_id: uuid.UUID, depth: int = 100) -> List[CommitHistoryItem]:
        """
        Get commit history by following parent_id chain.

        Args:
            commit_id: Starting commit ID
            depth: Maximum depth to traverse

        Returns:
            List of commit history items
        """
        commits = await self.repository.get_history(commit_id, depth)
        return [
            CommitHistoryItem(
                id=c.id,
                message=c.message,
                author_type=c.author_type,
                author_id=c.author_id,
                parent_id=c.parent_id,
                created_at=c.created_at,
                stats=c.stats,
            )
            for c in commits
        ]

    async def get_project_commits(self, project_id: uuid.UUID) -> List[Commit]:
        """
        Get all commits for a project.

        Args:
            project_id: Project ID

        Returns:
            List of commits, newest first
        """
        # Verify project exists
        await self.project_repo.get_by_id_or_raise(project_id)
        return await self.repository.get_by_project(project_id)

    async def get_commit_tree(self, project_id: uuid.UUID) -> List[CommitTree]:
        """
        Get the full commit history as a tree structure.

        Args:
            project_id: Project ID

        Returns:
            List of root commits with their children
        """
        # Get all commits for the project
        commits = await self.repository.get_by_project(project_id)

        # Build a map of commit_id -> commit
        commit_map = {c.id: c for c in commits}

        # Build tree structure
        root_commits = []
        children_map: dict[uuid.UUID, List[Commit]] = {}

        for commit in commits:
            if commit.parent_id is None:
                root_commits.append(commit)
            else:
                if commit.parent_id not in children_map:
                    children_map[commit.parent_id] = []
                children_map[commit.parent_id].append(commit)

        def build_tree(commit: Commit) -> CommitTree:
            children = children_map.get(commit.id, [])
            return CommitTree(
                id=commit.id,
                message=commit.message,
                parent_id=commit.parent_id,
                children=[build_tree(c) for c in children],
            )

        return [build_tree(r) for r in root_commits]

    async def get_commits_diff(
            self,
            from_commit_id: uuid.UUID,
            to_commit_id: uuid.UUID,
    ) -> CommitDiff:
        """
        Compare two commits and return the differences.

        Args:
            from_commit_id: Source commit ID
            to_commit_id: Target commit ID

        Returns:
            CommitDiff with added/removed samples and modified annotations
        """
        from saki_api.services.camap import CAMapService

        camap_service = CAMapService(self.session)

        # Get state for both commits
        from_state = await camap_service.get_annotations_for_commit(from_commit_id)
        to_state = await camap_service.get_annotations_for_commit(to_commit_id)

        # Get all sample IDs
        from_samples = set(from_state.keys())
        to_samples = set(to_state.keys())

        # Find added and removed samples
        added_samples = list(to_samples - from_samples)
        removed_samples = list(from_samples - to_samples)

        # Find modified annotations for common samples
        modified_annotations = {}
        common_samples = from_samples & to_samples

        for sample_id in common_samples:
            from_anns = set(from_state[sample_id])
            to_anns = set(to_state[sample_id])

            # Annotations in to but not in from = added
            # Annotations in from but not in to = removed
            added = list(to_anns - from_anns)
            removed = list(from_anns - to_anns)

            if added or removed:
                modified_annotations[sample_id] = {
                    "added": added,
                    "removed": removed,
                }

        return CommitDiff(
            from_commit_id=from_commit_id,
            to_commit_id=to_commit_id,
            added_samples=added_samples,
            removed_samples=removed_samples,
            modified_annotations=modified_annotations,
        )

    async def get_branch_head_commit(self, branch_id: uuid.UUID) -> Commit | None:
        """
        Get the HEAD commit of a branch.

        Args:
            branch_id: Branch ID

        Returns:
            Commit if found, None otherwise
        """
        return await self.repository.get_branch_head(branch_id)

    async def get_root_commit(self, project_id: uuid.UUID) -> Commit | None:
        """
        Get the root commit (parent_id is NULL) for a project.

        Args:
            project_id: Project ID

        Returns:
            Root commit if found, None otherwise
        """
        return await self.repository.find_root_commit(project_id)
