"""
User Role Service - Business logic for User-Role association operations.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import (
    BadRequestAppException,
    ForbiddenAppException,
    DataAlreadyExistsAppException,
)
from saki_api.infra.db.transaction import transactional
from saki_api.modules.access.api.user_system_role import UserSystemRoleRead, UserSystemRoleCreate, UserSystemRoleAssign
from saki_api.modules.access.domain.rbac.user_system_role import UserSystemRole
from saki_api.modules.access.repo.role import RoleRepository
from saki_api.modules.access.repo.user import UserRepository
from saki_api.modules.access.repo.user_system_role import UserSystemRoleRepository
from saki_api.modules.access.service.audit import (
    log_user_role_assign,
    log_user_role_revoke,
)
from saki_api.modules.access.service.guards import AdminGuard
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.shared.modeling import RoleType


class UserRoleService:
    """
    Service for user-role association business logic.
    
    Handles assignment and revocation of system roles to users,
    with proper validation and audit logging.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = UserSystemRoleRepository(session)
        self.user_repo = UserRepository(session)
        self.role_repo = RoleRepository(session)
        self.checker = PermissionChecker(session)

    async def get_user_roles(self, user_id: uuid.UUID) -> List[UserSystemRole]:
        """
        Get all system role assignments for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of UserSystemRole associations
        """
        return await self.repository.get_by_user(user_id)

    async def get_system_roles(self, user_id: uuid.UUID) -> List:
        """
        Get all system roles assigned to a user (Role objects).
        
        Args:
            user_id: User ID
            
        Returns:
            List of Role objects
        """
        return await self.repository.get_system_roles(user_id)

    @transactional
    async def _assign_role(
            self,
            user_id: uuid.UUID,
            role_id: uuid.UUID,
    ) -> UserSystemRole:
        """
        Assign a system role to a user (low-level method).

        Args:
            user_id: User ID
            role_id: Role ID to assign
            
        Returns:
            Created UserSystemRole association
            
        Raises:
            NotFoundAppException: If user not found
        """
        # Verify user exists
        await self.user_repo.get_by_id_or_raise(user_id)
        await self.role_repo.get_by_id_or_raise(role_id)

        role_in = UserSystemRoleCreate(
            user_id=user_id,
            role_id=role_id,
        )
        return await self.repository.assign(role_in)

    @transactional
    async def _revoke_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        """
        Revoke a system role from a user (low-level method).

        Args:
            user_id: User ID
            role_id: Role ID to revoke
            
        Returns:
            True if revoked, False if not found
        """
        return await self.repository.revoke(user_id, role_id)

    async def get_user_roles_read(
            self,
            user_id: uuid.UUID,
    ) -> List[UserSystemRoleRead]:
        """
        Get user's system roles with role details for response.
        """
        return await self.repository.get_by_user_with_roles(user_id)

    @transactional
    async def assign_user_system_role(
            self,
            user_id: uuid.UUID,
            role_in: UserSystemRoleAssign,
            current_user_id: uuid.UUID,
            guard: AdminGuard,
    ) -> UserSystemRoleRead:
        """
        Assign a system role to a user with full validation and audit logging.
        
        Args:
            user_id: User ID to assign role to (from URL path)
            role_in: Role assignment data (role_id and optional expires_at)
            
        Returns:
            UserSystemRoleRead with role details
            
        Raises:
            NotFoundAppException: If user or role not found
            BadRequestAppException: If role is not a system role
            ForbiddenAppException: If permission denied
            DataAlreadyExistsAppException: If role already assigned
        """
        # Verify user exists
        await self.user_repo.get_by_id_or_raise(user_id)

        # Verify role exists
        role = await self.role_repo.get_by_id_or_raise(role_in.role_id)

        if role.type != RoleType.SYSTEM:
            raise BadRequestAppException("Can only assign system roles through this endpoint")

        # Super admin cannot be assigned
        if role.is_super_admin:
            raise ForbiddenAppException("Super admin role cannot be assigned.")

        # Admin can only be assigned by super admin
        if role.is_admin and not await guard.is_super_admin(current_user_id):
            raise ForbiddenAppException("Admin role cannot be assigned by NON-Super admin.")

        # Check if already assigned
        user_roles = await self.repository.get_by_user(user_id)
        if any(ur.role_id == role_in.role_id for ur in user_roles):
            raise DataAlreadyExistsAppException("Role already assigned to user")

        # Create assignment
        assignment_data = UserSystemRoleCreate(
            user_id=user_id,
            role_id=role_in.role_id,
            expires_at=role_in.expires_at,
        )
        user_role = await self.repository.assign(assignment_data)

        # Audit log
        await log_user_role_assign(
            session=self.session,
            user_id=user_id,
            role_id=role_in.role_id
        )

        # Use model_validate to convert model to schema, then add role details
        role_read = UserSystemRoleRead.model_validate(user_role)
        role_read.role_name = role.name
        role_read.role_display_name = role.display_name
        return role_read

    @transactional
    async def revoke_user_system_role(
            self,
            user_id: uuid.UUID,
            role_id: uuid.UUID,
            current_user_id: uuid.UUID,
            guard: AdminGuard,
    ) -> bool:
        """
        Revoke a system role with full validation and audit logging.
        
        Args:
            user_id: User ID to revoke role from
            role_id: Role ID to revoke
            
        Returns:
            True if revoked successfully
            
        Raises:
            NotFoundAppException: If role assignment not found
            ForbiddenAppException: If permission denied or trying to revoke from self
        """
        # Check if role is assigned
        await self.repository.get_by_user_and_role_or_raise(user_id, role_id)

        role = await self.role_repo.get_by_id_or_raise(role_id)

        if role.is_super_admin:
            raise ForbiddenAppException("Super admin role cannot be revoked.")

        if role.is_admin and not await guard.is_super_admin(current_user_id):
            raise ForbiddenAppException("Admin role can ONLY be revoked by Super admin")

        # Audit log
        await log_user_role_revoke(
            session=self.session,
            user_id=user_id,
            role_id=role_id,
        )

        result = await self.repository.revoke(user_id, role_id)
        return result
