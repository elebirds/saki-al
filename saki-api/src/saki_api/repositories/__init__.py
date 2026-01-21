"""
Repository layer for data access abstraction.
"""

from saki_api.repositories.permission_repository import PermissionRepository
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_repository import UserRepository

__all__ = [
    "UserRepository",
    "RoleRepository",
    "PermissionRepository",
]
