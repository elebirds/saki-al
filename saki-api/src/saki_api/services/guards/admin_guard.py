"""
Admin Guard - Guards for admin and super admin authorization checks.
"""

import uuid
from typing import Optional

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.rbac import PermissionChecker, get_permission_checker
from saki_api.core.rbac.dependencies import get_current_user
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.models.user import User


class AdminGuard:
    """
    Guard for admin and super admin authorization checks.
    
    Provides methods to check admin status and protect admin operations.
    """

    def __init__(self, checker: PermissionChecker):
        self.checker = checker

    async def is_super_admin(self, user_id: uuid.UUID) -> bool:
        """Check if user is a super admin."""
        return await self.checker.is_super_admin(user_id)

    async def is_admin(self, user_id: uuid.UUID) -> bool:
        """Check if user is an admin (including super admin)."""
        return await self.checker.is_admin(user_id)

    async def protect_super_admin(
        self,
        target_user_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> None:
        """
        Protect super admin accounts from being modified by non-super admins.
        
        Args:
            target_user_id: ID of the user being modified
            current_user_id: ID of the current user performing the action
            
        Raises:
            HTTPException: If target is super admin and current user is not super admin
        """
        if await self.checker.is_super_admin(target_user_id):
            if not await self.checker.is_super_admin(current_user_id):
                raise ForbiddenAppException(
                    "Only super administrators can modify super administrator accounts"
                )

    async def protect_super_admin_deletion(
        self,
        target_user_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> None:
        """
        Protect super admin accounts from being deleted.
        
        Prevents:
        1. Non-super admins from deleting super admin accounts
        2. Super admins from deleting themselves
        
        Args:
            target_user_id: ID of the user being deleted
            current_user_id: ID of the current user performing the action
            
        Raises:
            HTTPException: If deletion is not allowed
        """
        if await self.checker.is_super_admin(target_user_id):
            if not await self.checker.is_super_admin(current_user_id):
                raise ForbiddenAppException(
                    "Only super administrators can delete super administrator accounts"
                )
            if target_user_id == current_user_id:
                raise ForbiddenAppException(
                    "Super administrators cannot delete themselves"
                )


async def get_admin_guard(
    checker: PermissionChecker = Depends(get_permission_checker),
) -> AdminGuard:
    """Dependency to get an AdminGuard instance."""
    return AdminGuard(checker)


async def require_super_admin(
    current_user: User = Depends(get_current_user),
    checker: PermissionChecker = Depends(get_permission_checker),
) -> User:
    """
    FastAPI dependency that requires super admin privileges.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: User = Depends(require_super_admin),
        ):
            ...
    """
    guard = AdminGuard(checker)
    if not await guard.is_super_admin(current_user.id):
        raise ForbiddenAppException("The user doesn't have enough privileges")
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user),
    checker: PermissionChecker = Depends(get_permission_checker),
) -> User:
    """
    FastAPI dependency that requires admin privileges (including super admin).
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: User = Depends(require_admin),
        ):
            ...
    """
    guard = AdminGuard(checker)
    if not await guard.is_admin(current_user.id):
        raise ForbiddenAppException("The user doesn't have enough privileges")
    return current_user
