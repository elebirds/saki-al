"""
Auth Service - Authentication and password management logic.
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from saki_api.core import security
from saki_api.core.config import settings
from saki_api.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def login_access_token(self, form_data: OAuth2PasswordRequestForm) -> Dict[str, Any]:
        """Authenticate the user and issue an access token."""
        user = await self.user_repo.get_by_email(form_data.username)
        if not user or not security.verify_password(form_data.password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Incorrect email or password")
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")

        # Update last login time
        user.last_login_at = datetime.utcnow()
        await self.user_repo.update(user.id, {"last_login_at": user.last_login_at})
        await self.user_repo.commit()

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        response: Dict[str, Any] = {
            "access_token": security.create_access_token(
                user.id, expires_delta=access_token_expires
            ),
            "token_type": "bearer",
        }
        if user.must_change_password:
            response["must_change_password"] = True
        return response

    async def change_password(self, current_user, old_password: str, new_password: str) -> Dict[str, str]:
        """Change password for the current user after verifying the old one and format."""
        # Verify old password
        if not security.verify_password(old_password, current_user.hashed_password):
            raise HTTPException(status_code=400, detail="Incorrect old password")

        # Verify new password format
        if not security.is_frontend_hashed_password(new_password):
            raise HTTPException(
                status_code=400,
                detail="New password must be in the correct format (frontend hashed)",
            )

        await self.user_repo.update(
            current_user.id,
            {
                "hashed_password": security.get_password_hash(new_password),
                "must_change_password": False,
            },
        )
        await self.user_repo.commit()
        await self.user_repo.refresh(current_user)
        return {"message": "Password changed successfully"}
