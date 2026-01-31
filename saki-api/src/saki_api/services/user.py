"""
User Service - Business logic for User operations.
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlmodel.ext.asyncio.session import AsyncSession
from typing_extensions import override

from saki_api.core import security
from saki_api.core.exceptions import (
    DataAlreadyExistsAppException,
)
from saki_api.db.transaction import transactional
from saki_api.models.user import User
from saki_api.repositories.user import UserRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas import UserRead
from saki_api.services.base import BaseService
from saki_api.services.guards.admin_guard import AdminGuard
from saki_api.schemas.user import UserUpdate, UserCreate


class UserService(BaseService[User, UserRepository, UserCreate, UserUpdate]):
    """Service for user business logic."""

    def __init__(self, session: AsyncSession):
        super().__init__(User, UserRepository, session)

    async def has_any_user(self):
        return await self.repository.exists()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return await self.repository.get_by_email(email)

    async def list_active(self, pagination: Pagination) -> List[User]:
        """List active users for member selection."""
        return await self.repository.list_active(pagination)

    async def get_profile_by_id(self, user_id: uuid.UUID) -> UserRead:
        return await self.repository.get_with_roles_by_id(user_id)

    async def list_with_roles(self, pagination: Pagination) -> List[UserRead]:
        return await self.repository.list_with_roles(pagination=pagination)

    @transactional
    @override
    async def create(self, user_in: UserCreate, must_change_password: bool = True) -> User:
        # Check email uniqueness
        if await self.repository.get_by_email(user_in.email):
            raise DataAlreadyExistsAppException(
                "The user with this email already exists in the system."
            )

        # Hash password
        hashed_password = security.get_password_hash(user_in.password)

        # Create user with must_change_password flag
        user_data = user_in.model_dump(exclude={"password"})
        user_data["hashed_password"] = hashed_password
        user_data["must_change_password"] = must_change_password

        return await self.repository.create(user_data)

    @transactional
    async def update_user(
        self,
        user_id: uuid.UUID,
        user_in: UserUpdate,
        guard: AdminGuard,
        current_user_id: uuid.UUID,
    ) -> User:
        """
        Update a user.
        
        Args:
            user_id: User ID to update
            user_in: Update data
            guard: AdminGuard for permission checks
            current_user_id: ID of the current user performing the action
        """
        # Protect super admin
        await guard.protect_super_admin(user_id, current_user_id)

        # Prepare update data
        user_data = user_in.model_dump(exclude_unset=True)

        # Handle password hashing
        if "password" in user_data:
            password = user_data.pop("password")
            if password:
                user_data["hashed_password"] = security.get_password_hash(password)

        # Update user
        return await self.repository.update_or_raise(user_id, user_data)

    @transactional
    async def delete_user(
        self,
        user_id: uuid.UUID,
        guard: AdminGuard,
        current_user_id: uuid.UUID,
    ) -> User:
        """
        Delete a user.
        
        Args:
            user_id: User ID to delete
            guard: AdminGuard for permission checks
            current_user_id: ID of the current user performing the action
        
        Raises:
            HTTPException: If user not found or permission denied
        """
        # Protect super admin
        await guard.protect_super_admin_deletion(user_id, current_user_id)
        return await self.delete(user_id)

    @transactional
    async def update_user_login_time(
        self,
        user_id: uuid.UUID,
    ):
        await self.repository.update(user_id, {"last_login_at": datetime.utcnow()})

    @transactional
    async def change_password(
            self,
            record_id: uuid.UUID,
            hashed_password: str,
            must_change_password: bool
    ) -> User:
        return await self.repository.update_or_raise(record_id, {"password": hashed_password,
                                                                 "must_change_password": must_change_password})