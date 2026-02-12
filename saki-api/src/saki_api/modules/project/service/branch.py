"""
Branch Service - Business logic for Branch operations.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException, DataAlreadyExistsAppException, BadRequestAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.api.branch import BranchCreate, BranchUpdate
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.repo import ProjectRepository
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.project.repo.commit import CommitRepository
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class BranchService(CrudServiceBase[Branch, BranchRepository, BranchCreate, BranchUpdate]):
    """
    Service for managing Branches.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Branch, BranchRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.commit_repo = CommitRepository(session)

    @transactional
    async def create_branch(
            self,
            project_id: uuid.UUID,
            name: str,
            from_commit_id: uuid.UUID,
            description: str | None = None,
    ) -> Branch:
        """
        Create a new branch from a commit.

        Args:
            project_id: Project ID
            name: Branch name
            from_commit_id: Commit to branch from
            description: Optional branch description

        Returns:
            Created branch

        Raises:
            NotFoundAppException: If project or commit not found
            DataAlreadyExistsAppException: If branch name already exists
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        # Verify commit exists
        commit = await self.commit_repo.get_by_id(from_commit_id)
        if not commit:
            raise NotFoundAppException(f"Commit {from_commit_id} not found")

        if commit.project_id != project_id:
            raise BadRequestAppException("Commit must belong to the same project")

        # Check if branch name already exists
        if await self.repository.name_exists(project_id, name):
            raise DataAlreadyExistsAppException(
                f"Branch '{name}' already exists in this project"
            )

        branch_data = BranchCreate(
            project_id=project_id,
            name=name,
            head_commit_id=from_commit_id,
            description=description,
            is_protected=False,
        )

        return await self.create(branch_data)

    @transactional
    async def switch_to_commit(
            self,
            branch_id: uuid.UUID,
            target_commit_id: uuid.UUID,
    ) -> Branch:
        """
        Move branch HEAD to a different commit (git checkout equivalent).

        Args:
            branch_id: Branch ID
            target_commit_id: Target commit ID

        Returns:
            Updated branch

        Raises:
            NotFoundAppException: If branch or commit not found
            BadRequestAppException: If commit is from different project
        """
        branch = await self.get_by_id_or_raise(branch_id)

        # Prevent modifying protected branches
        if branch.is_protected:
            raise BadRequestAppException("Cannot modify protected branch")

        # Verify commit exists
        commit = await self.commit_repo.get_by_id(target_commit_id)
        if not commit:
            raise NotFoundAppException(f"Commit {target_commit_id} not found")

        if commit.project_id != branch.project_id:
            raise BadRequestAppException("Commit must belong to the same project")

        # Update HEAD
        return await self.repository.update_head(branch_id, target_commit_id)

    async def get_project_branches(self, project_id: uuid.UUID) -> List[Branch]:
        """
        Get all branches for a project.

        Args:
            project_id: Project ID

        Returns:
            List of branches
        """
        # Verify project exists
        await self.project_repo.get_by_id_or_raise(project_id)
        return await self.repository.get_by_project(project_id)

    async def get_project_branches_with_head(self, project_id: uuid.UUID) -> List[dict]:
        """
        Get all branches for a project with HEAD commit info.

        Args:
            project_id: Project ID

        Returns:
            List of branches with head_commit info
        """
        branches = await self.repository.get_by_project_with_head(project_id)

        result = []
        for branch in branches:
            # Access the preloaded head_commit
            head_commit = branch.head_commit if hasattr(branch, 'head_commit') else None
            result.append({
                "id": branch.id,
                "name": branch.name,
                "head_commit_id": branch.head_commit_id,
                "head_commit_message": head_commit.message if head_commit else None,
                "description": branch.description,
                "is_protected": branch.is_protected,
                "created_at": branch.created_at,
                "updated_at": branch.updated_at,
            })

        return result

    async def get_master_branch(self, project_id: uuid.UUID) -> Branch:
        """
        Get the master branch for a project.

        Args:
            project_id: Project ID

        Returns:
            Master branch

        Raises:
            NotFoundAppException: If master branch not found
        """
        branch = await self.repository.get_master_branch(project_id)
        if not branch:
            raise NotFoundAppException(f"Master branch for project {project_id} not found")
        return branch

    @transactional
    async def update_branch(
            self,
            branch_id: uuid.UUID,
            name: str | None = None,
            description: str | None = None,
            is_protected: bool | None = None,
    ) -> Branch:
        """
        Update branch metadata.

        Note: Use switch_to_commit to change HEAD.

        Args:
            branch_id: Branch ID
            name: New name (optional)
            description: New description (optional)
            is_protected: New protected status (optional)

        Returns:
            Updated branch

        Raises:
            NotFoundAppException: If branch not found
            DataAlreadyExistsAppException: If new name conflicts
        """
        branch = await self.get_by_id_or_raise(branch_id)

        if branch.name == "master" and is_protected is not None and is_protected is False:
            raise BadRequestAppException("Cannot unprotect master branch")

        # Check name conflict if changing name
        if name and name != branch.name:
            if await self.repository.name_exists(branch.project_id, name, exclude_id=branch_id):
                raise DataAlreadyExistsAppException(
                    f"Branch '{name}' already exists in this project"
                )

        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if is_protected is not None:
            update_data["is_protected"] = is_protected

        return await self.repository.update(branch_id, update_data)

    @transactional
    async def delete_branch(self, branch_id: uuid.UUID) -> bool:
        """
        Delete a branch.

        Args:
            branch_id: Branch ID

        Returns:
            True if deleted, False if not found

        Raises:
            BadRequestAppException: If trying to delete protected branch
        """
        branch = await self.get_by_id(branch_id)
        if not branch:
            return False

        if branch.name == "master":
            raise BadRequestAppException("Cannot delete master branch")

        if branch.is_protected:
            raise BadRequestAppException("Cannot delete protected branch")

        return await self.repository.delete(branch_id)
