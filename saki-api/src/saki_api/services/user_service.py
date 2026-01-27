"""
User Service - Business logic for User operations.
"""

import uuid
from typing import Optional, List

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core import security
from saki_api.core.rbac import PermissionChecker
from saki_api.core.rbac.audit import (
    log_user_role_assign,
    log_user_role_revoke,
)
from saki_api.core.rbac.presets import get_default_role
from saki_api.models import User, UserSystemRole, RoleType
from saki_api.models.rbac.enums import Permissions
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_repository import UserRepository
from saki_api.schemas import (
    UserRead,
    UserUpdate,
    UserCreate,
    UserSystemRoleCreate,
    UserSystemRoleRead,
)
from saki_api.services.base_service import BaseService


class UserService(BaseService[User, UserCreate, UserUpdate]):
    """Service for user business logic."""

    def __init__(self, session: AsyncSession, current_user: Optional[User] = None):
        super().__init__(User, session, current_user)
        # Override repository with UserRepository for additional methods
        self.repo = UserRepository(session)

    # Keep custom methods that extend BaseService functionality
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return await self.repo.get_by_email(email)

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List all users."""
        return await self.list_all(skip=skip, limit=limit)

    async def list_active_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List active users for member selection."""
        return await self.repo.list_active(skip=skip, limit=limit)

    async def create_user(self, user_in: UserCreate) -> User:
        """
        Create a new user.
        
        Args:
            user_in: User creation data
        
        Raises:
            HTTPException: If email already exists
        """
        # Check email uniqueness
        existing_user = await self.repo.get_by_email(user_in.email)
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="The user with this email already exists in the system.",
            )

        # Hash password
        hashed_password = security.get_password_hash(user_in.password)

        # Create user with must_change_password flag
        user_data = user_in.model_dump(exclude={"password"})
        user_data["hashed_password"] = hashed_password
        user_data["must_change_password"] = True

        user = await self.repo.create(user_data)

        # Assign default role
        default_role = await get_default_role(self.repo.session)
        if default_role:
            assigned_by = self.current_user.id if self.current_user else "system"
            await self.repo.assign_system_role(user.id, default_role.id, assigned_by)

        await self.repo.commit()
        await self.repo.refresh(user)
        return user

    async def update_user(self, user_id: uuid.UUID, user_in: UserUpdate, checker: PermissionChecker) -> User:
        """
        Update a user.
        
        Args:
            user_id: User ID to update
            user_in: Update data
            checker: Permission checker for super admin checks
        
        Raises:
            HTTPException: If user not found or permission denied
        """
        user = await self.get_by_id(user_id)

        # Protect super admin
        if await checker.is_super_admin(user_id):
            if not await checker.is_super_admin(self.current_user.id):
                raise HTTPException(
                    status_code=403,
                    detail="Only super administrators can modify super administrator accounts"
                )

        # Prepare update data
        user_data = user_in.model_dump(exclude_unset=True)

        # Handle password hashing
        if "password" in user_data:
            password = user_data.pop("password")
            if password:
                user_data["hashed_password"] = security.get_password_hash(password)

        # Update user
        user = await self.repo.update(user_id, user_data)
        await self.repo.commit()
        await self.repo.refresh(user)
        return user

    async def delete_user(self, user_id: uuid.UUID, checker: PermissionChecker) -> User:
        """
        Delete a user.
        
        Args:
            user_id: User ID to delete
            checker: Permission checker for super admin checks
        
        Raises:
            HTTPException: If user not found or permission denied
        """
        user = await self.get_by_id(user_id)

        # Protect super admin
        if checker.is_super_admin(user_id):
            if not checker.is_super_admin(self.current_user.id):
                raise HTTPException(
                    status_code=403,
                    detail="Only super administrators can delete super administrator accounts"
                )

            if user_id == self.current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Super administrators cannot delete themselves"
                )

        # Use BaseService delete method
        return await self.delete(user_id)

    async def build_user_read(self, user: User) -> UserRead:
        """
        Build UserRead response with role information.
        
        Args:
            user: User object
        
        Returns:
            UserRead with roles populated
        """
        # Get system roles
        user_roles = await self.repo.get_system_roles(user.id)

        # Convert roles to dictionaries
        roles_dicts = [
            {
                "id": str(role.id),
                "name": role.name,
                "displayName": role.display_name,
            }
            for role in user_roles
        ]

        # Build response without triggering lazy loads
        return UserRead(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            avatar_url=user.avatar_url,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
            system_roles=roles_dicts,
        )

    async def get_user_roles(self, user_id: uuid.UUID) -> List[UserSystemRole]:
        """Get all system roles assigned to a user."""
        return await self.repo.get_user_system_roles(user_id)

    async def assign_role(self, user_id: uuid.UUID, role_id: uuid.UUID, current_user_id: uuid.UUID) -> UserSystemRole:
        """Assign a system role to a user."""
        # Verify user exists
        await self.get_by_id(user_id)

        return await self.repo.assign_system_role(user_id, role_id, current_user_id)

    async def revoke_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        """Revoke a system role from a user."""
        return await self.repo.revoke_system_role(user_id, role_id)

    # =====================================================================
    # System role management with business checks for controllers
    # =====================================================================

    async def get_user_roles_read(
            self,
            user_id: uuid.UUID,
            role_repo: RoleRepository,
    ) -> List[UserSystemRoleRead]:
        """Get user's system roles with role details for response."""
        # Ensure user exists (raise 404 if not)
        await self.get_by_id(user_id)

        user_roles = await self.repo.get_user_system_roles(user_id)

        result: List[UserSystemRoleRead] = []
        for ur in user_roles:
            role = await role_repo.get_by_id(ur.role_id)
            result.append(UserSystemRoleRead(
                id=ur.id,
                user_id=ur.user_id,
                role_id=ur.role_id,
                assigned_at=ur.assigned_at,
                assigned_by=ur.assigned_by,
                expires_at=ur.expires_at,
                role_name=role.name if role else None,
                role_display_name=role.display_name if role else None,
            ))

        return result

    async def assign_user_system_role(
            self,
            user_id: uuid.UUID,
            role_in: UserSystemRoleCreate,
            current_user: User,
            checker: PermissionChecker,
            role_repo: RoleRepository,
    ) -> UserSystemRoleRead:
        """Assign a system role to a user with validations and audit logging."""
        from fastapi import HTTPException

        # Verify user exists
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify role exists
        role = await role_repo.get_by_id(role_in.role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        if role.type != RoleType.SYSTEM:
            raise HTTPException(
                status_code=400,
                detail="Can only assign system roles through this endpoint"
            )

        # Super admin cannot be assigned
        if role.is_super_admin:
            raise HTTPException(
                status_code=403,
                detail="super_admin role cannot be assigned through this endpoint"
            )

        # Admin role requires elevated permission
        if role.is_admin:
            if not await checker.check(current_user.id, Permissions.ROLE_ASSIGN_ADMIN):
                # Keep string literal to avoid tight import coupling; controller uses Permissions enum
                raise HTTPException(
                    status_code=403,
                    detail="Only super administrators can assign admin roles"
                )

        # Already assigned?
        user_roles = await self.repo.get_user_system_roles(user_id)
        if any(ur.role_id == role_in.role_id for ur in user_roles):
            raise HTTPException(
                status_code=400,
                detail="Role already assigned to user"
            )

        # Create assignment
        user_role = await self.repo.assign_system_role(user_id, role_in.role_id, current_user.id)

        # Audit log
        log_user_role_assign(
            session=self.repo.session,
            user_id=user_id,
            role_id=role_in.role_id,
            actor_id=current_user.id,
        )

        await self.repo.commit()
        await self.repo.refresh(user_role)

        return UserSystemRoleRead(
            id=user_role.id,
            user_id=user_role.user_id,
            role_id=user_role.role_id,
            assigned_at=user_role.assigned_at,
            assigned_by=user_role.assigned_by,
            expires_at=user_role.expires_at,
            role_name=role.name,
            role_display_name=role.display_name,
        )

    async def revoke_user_system_role(
            self,
            user_id: uuid.UUID,
            role_id: uuid.UUID,
            current_user: User,
            checker: PermissionChecker,
            role_repo: RoleRepository,
    ) -> bool:
        """Revoke a system role with validations and audit."""
        from fastapi import HTTPException

        # Check if role is assigned
        user_roles = await self.repo.get_user_system_roles(user_id)
        user_role = next((ur for ur in user_roles if ur.role_id == role_id), None)
        if not user_role:
            raise HTTPException(status_code=404, detail="Role not assigned to user")

        role = await role_repo.get_by_id(role_id)

        # Admin/super_admin checks
        if role and (role.is_super_admin or role.is_admin):
            if not await checker.check(current_user.id, Permissions.ROLE_ASSIGN_ADMIN):
                raise HTTPException(
                    status_code=403,
                    detail="Only super administrators can revoke super_admin or admin roles"
                )
            if user_id == current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Cannot revoke super_admin or admin role from yourself"
                )

        # Audit log
        log_user_role_revoke(
            session=self.repo.session,
            user_id=user_id,
            role_id=role_id,
            actor_id=current_user.id,
        )

        result = await self.repo.revoke_system_role(user_id, role_id)
        await self.repo.commit()
        return result
