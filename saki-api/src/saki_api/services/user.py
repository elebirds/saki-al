"""
User Service - Business logic for User operations.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import UploadFile
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession
from typing_extensions import override

from saki_api.core import security
from saki_api.core.exceptions import (
    BadRequestAppException,
    DataAlreadyExistsAppException,
)
from saki_api.db.transaction import transactional
from saki_api.models.user import User
from saki_api.repositories.query import Pagination
from saki_api.repositories.user import UserRepository
from saki_api.schemas import UserRead
from saki_api.schemas.pagination import PaginationResponse
from saki_api.schemas.user import UserUpdate, UserCreate
from saki_api.services.asset import AssetService
from saki_api.services.base import BaseService
from saki_api.services.guards import AdminGuardDep


class UserService(BaseService[User, UserRepository, UserCreate, UserUpdate]):
    """Service for user business logic."""

    AVATAR_ASSET_URI_PREFIX = "asset://"
    AVATAR_SIGNED_URL_EXPIRE_HOURS = 24
    AVATAR_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
    AVATAR_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}

    def __init__(self, session: AsyncSession):
        super().__init__(User, UserRepository, session)
        self.asset_service = AssetService(session=session)

    @classmethod
    def build_avatar_asset_uri(cls, asset_id: uuid.UUID) -> str:
        return f"{cls.AVATAR_ASSET_URI_PREFIX}{asset_id}"

    @classmethod
    def parse_avatar_asset_id(cls, avatar_url: Optional[str]) -> Optional[uuid.UUID]:
        if not avatar_url or not avatar_url.startswith(cls.AVATAR_ASSET_URI_PREFIX):
            return None
        raw = avatar_url[len(cls.AVATAR_ASSET_URI_PREFIX):].strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @classmethod
    def _is_allowed_avatar_file(cls, file: UploadFile) -> bool:
        content_type = (file.content_type or "").lower()
        if content_type:
            return content_type in cls.AVATAR_ALLOWED_MIME_TYPES
        filename = (file.filename or "").lower()
        return filename.endswith((".png", ".jpg", ".jpeg", ".webp"))

    async def resolve_avatar_url(self, avatar_url: Optional[str]) -> Optional[str]:
        asset_id = self.parse_avatar_asset_id(avatar_url)
        if not asset_id:
            return avatar_url
        try:
            return await self.asset_service.get_presigned_download_url(
                asset_id=asset_id,
                expires_in_hours=self.AVATAR_SIGNED_URL_EXPIRE_HOURS,
            )
        except Exception as exc:
            logger.warning("解析用户头像 URL 失败 asset_id={} error={}", asset_id, exc)
            return None

    async def _hydrate_user_read(self, user: Optional[UserRead]) -> Optional[UserRead]:
        if user is None:
            return None
        user.avatar_url = await self.resolve_avatar_url(user.avatar_url)
        return user

    async def has_any_user(self):
        return await self.repository.exists()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return await self.repository.get_by_email(email)

    async def list_active_paginated(
            self,
            pagination: Pagination,
            q: str | None = None,
    ) -> PaginationResponse[User]:
        """List active users for member selection."""
        return await self.repository.list_active_paginated(pagination, q=q)

    async def get_profile_by_id(self, user_id: uuid.UUID) -> UserRead:
        user = await self.repository.get_with_roles_by_id(user_id)
        return await self._hydrate_user_read(user)

    async def list_with_roles_paginated(self, pagination: Pagination) -> PaginationResponse[UserRead]:
        paged = await self.repository.list_with_roles_paginated(pagination=pagination)
        return await paged.map_async(self._hydrate_user_read)

    @transactional
    async def upload_current_user_avatar(self, user_id: uuid.UUID, file: UploadFile) -> UserRead:
        if not self._is_allowed_avatar_file(file):
            raise BadRequestAppException(
                "Avatar must be PNG/JPEG/WebP image."
            )

        payload = await file.read()
        if not payload:
            raise BadRequestAppException("Avatar file is empty.")
        if len(payload) > self.AVATAR_MAX_FILE_SIZE_BYTES:
            raise BadRequestAppException(
                f"Avatar file exceeds {self.AVATAR_MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB limit."
            )

        file.file.seek(0)
        asset = await self.asset_service.upload_file(file)
        await self.repository.update_or_raise(
            user_id,
            {"avatar_url": self.build_avatar_asset_uri(asset.id)},
        )
        profile = await self.get_profile_by_id(user_id)
        if profile is None:
            raise BadRequestAppException("User not found after avatar upload.")
        return profile

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
            current_user_id: uuid.UUID,
            guard: AdminGuardDep
    ) -> User:
        """
        Update a user.
        
        Args:
            user_id: User ID to update
            user_in: Update data
            current_user_id: ID of the current user performing the action
            guard: AdminGuard for permission checks
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
            current_user_id: uuid.UUID,
            guard: AdminGuardDep
    ) -> User:
        """
        Delete a user.
        
        Args:
            user_id: User ID to delete
            current_user_id: ID of the current user performing the action
            guard: AdminGuard for permission checks
        
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
