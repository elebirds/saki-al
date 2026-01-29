"""
Token Service - Token creation and validation logic.

This service handles all token-related operations including:
- Access token creation
- Refresh token creation and validation
- Token payload extraction
"""
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from jose import jwt, JWTError
from pydantic import ValidationError

from saki_api.core.config import settings
from saki_api.core.exceptions import AuthInvalidTokenAppException


class TokenService:
    """Service for token operations."""

    @staticmethod
    def create_access_token(user_id: uuid.UUID, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create an access token for a user.
        
        Args:
            user_id: User ID to encode in token
            expires_delta: Optional expiration delta. If None, uses default from settings.
            
        Returns:
            Encoded JWT access token
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode = {"exp": expire, "sub": str(user_id), "type": "access"}
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt

    @staticmethod
    def create_refresh_token(user_id: uuid.UUID, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a refresh token for a user.
        
        Refresh tokens have a longer expiration time than access tokens.
        
        Args:
            user_id: User ID to encode in token
            expires_delta: Optional expiration delta. Defaults to 7 days.
            
        Returns:
            Encoded JWT refresh token
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            # Default refresh token expiration: 7 days
            expire = datetime.utcnow() + timedelta(days=7)

        to_encode = {"exp": expire, "sub": str(user_id), "type": "refresh"}
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """
        Decode and validate a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload
            
        Raises:
            AuthInvalidTokenAppException: If token is invalid or expired
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            return payload
        except (JWTError, ValidationError) as e:
            raise AuthInvalidTokenAppException("Invalid or expired token") from e

    @staticmethod
    def extract_user_id_from_token(token: str) -> uuid.UUID:
        """
        Extract user ID from a token.
        
        Args:
            token: JWT token string
            
        Returns:
            User ID from token
            
        Raises:
            AuthInvalidTokenAppException: If token is invalid or expired
        """
        payload = TokenService.decode_token(token)
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise AuthInvalidTokenAppException("Token missing user ID")
        return uuid.UUID(user_id_str)

    @staticmethod
    def is_refresh_token(token: str) -> bool:
        """
        Check if a token is a refresh token.
        
        Args:
            token: JWT token string
            
        Returns:
            True if token is a refresh token, False otherwise
            
        Raises:
            AuthInvalidTokenAppException: If token is invalid or expired
        """
        payload = TokenService.decode_token(token)
        return payload.get("type") == "refresh"

    @staticmethod
    def create_token_pair(user_id: uuid.UUID) -> Dict[str, str]:
        """
        Create both access and refresh tokens for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with access_token and refresh_token
        """
        return {
            "access_token": TokenService.create_access_token(user_id),
            "refresh_token": TokenService.create_refresh_token(user_id),
            "token_type": "bearer",
        }
