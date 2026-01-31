"""
Auth Service - Authentication and password management logic.

This service orchestrates authentication operations by coordinating between:
- UserService: User data operations
- TokenService: Token creation and validation
"""
import logging
import uuid
from typing import Any, Dict

from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core import security
from saki_api.core.exceptions import (
    AuthInvalidCredentialsAppException,
    AuthInactiveUserAppException,
    AuthIncorrectPasswordAppException,
    AuthInvalidTokenAppException,
    DataInvalidFormatAppException,
)
from saki_api.db.transaction import transactional
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.user_system_role import UserSystemRoleRepository
from saki_api.schemas import UserCreate, UserRead
from saki_api.schemas.auth import LoginResponse
from saki_api.services.token_service import TokenService
from saki_api.services.user import UserService

logger = logging.getLogger(__name__)

class AuthService:
    """
    Authentication service that orchestrates user authentication operations.
    
    This service coordinates between UserService and TokenService to provide
    high-level authentication operations like login, registration, and token refresh.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_service = UserService(session)
        self.token_service = TokenService()
        self.role_repo = RoleRepository(session)
        self.user_role_repo = UserSystemRoleRepository(session)

    @transactional
    async def login(self, form_data: OAuth2PasswordRequestForm) -> LoginResponse:
        """
        Authenticate the user and issue access and refresh tokens.
        
        Args:
            form_data: OAuth2 password request form containing username (email) and password
            
        Returns:
            Dictionary containing access_token, refresh_token, token_type, and must_change_password
            
        Raises:
            AuthInvalidCredentialsAppException: If credentials are invalid
            AuthInactiveUserAppException: If user is inactive
        """
        user = await self.user_service.get_by_email(form_data.username)
        if not user or not security.verify_password(form_data.password, user.hashed_password):
            raise AuthInvalidCredentialsAppException("Incorrect email or password")
        if not user.is_active:
            raise AuthInactiveUserAppException("Inactive user")

        await self.user_service.update_user_login_time(user.id)

        return LoginResponse(
            access_token=TokenService.create_access_token(user.id),
            refresh_token=TokenService.create_refresh_token(user.id),
            must_change_password=user.must_change_password
        )

    @transactional
    async def register(self, user_in: UserCreate):
        """
        Register a new user.
        
        Args:
            user_in: User creation data
            
        Returns:
            UserRead: Created user profile
            
        Note:
            New users are automatically assigned the default system role.
        """
        user = await self.user_service.create(user_in, must_change_password=False)

        # Assign default role to new user
        await self._assign_default_role_to_user(user.id)

    async def _assign_default_role_to_user(self, user_id: uuid.UUID) -> None:
        """
        Assign the default system role to a user.
        
        This is a helper method used during user registration.
        Audit fields (created_by, updated_by) are automatically populated
        by event listeners from the current user context.
        
        Args:
            user_id: ID of the user to assign the role to
        """
        from saki_api.schemas.user_system_role import UserSystemRoleCreate
        
        default_role = await self.role_repo.get_default()
        if not default_role:
            # If no default role exists, skip assignment (should not happen in normal flow)
            logger.error(f"Default role not found for user {user_id}")
            return
        
        role_in = UserSystemRoleCreate(
            user_id=user_id,
            role_id=default_role.id,
        )
        await self.user_role_repo.assign(role_in)

    @transactional
    async def refresh_access_token(self, refresh_token: str) -> LoginResponse:
        """
        Refresh an access token using a refresh token.
        
        Args:
            refresh_token: Valid refresh token string
            
        Returns:
            Dictionary containing new access_token and token_type
            
        Raises:
            AuthInvalidTokenAppException: If refresh token is invalid or expired
        """
        # Validate that it's actually a refresh token
        if not self.token_service.is_refresh_token(refresh_token):
            raise AuthInvalidTokenAppException("Token is not a refresh token")
        
        # Extract user ID from refresh token
        user_id = self.token_service.extract_user_id_from_token(refresh_token)
        
        # Verify user exists and is active
        user = await self.user_service.get_by_id(user_id)
        if not user:
            raise AuthInvalidTokenAppException("User not found")
        if not user.is_active:
            raise AuthInactiveUserAppException("Inactive user")
        
        # Create new access token
        return LoginResponse(
            access_token=TokenService.create_access_token(user.id),
            refresh_token=refresh_token,
            must_change_password=user.must_change_password
        )

    @transactional
    async def change_password(self, user_id: uuid.UUID, old_password: str, new_password: str):
        """
        Change user password.
        
        Args:
            user_id: ID of the user changing password
            old_password: Current password (frontend hashed)
            new_password: New password (frontend hashed)
            
        Returns:
            Success message
            
        Raises:
            AuthIncorrectPasswordAppException: If old password is incorrect
            DataInvalidFormatAppException: If new password format is invalid
        """
        user = await self.user_service.get_by_id(user_id)

        # Verify old password
        if not security.verify_password(old_password, user.hashed_password):
            raise AuthIncorrectPasswordAppException("Incorrect old password")

        # Verify new password format
        if not security.is_frontend_hashed_password(new_password):
            raise DataInvalidFormatAppException(
                "New password must be in the correct format (frontend hashed)"
            )

        await self.user_service.change_password(
            user.id, 
            security.get_password_hash(new_password), 
            False
        )
