"""
Permission Query Schemas

Schemas for permission query responses, separated into system and resource permissions.
"""

import uuid
from typing import List, Optional

from pydantic import BaseModel


class RoleInfo(BaseModel):
    """Basic role information."""
    id: uuid.UUID
    name: str
    displayName: str


class SystemPermissionsResponse(BaseModel):
    """
    Response for system-level permissions endpoint.
    
    Contains permissions from system roles only.
    """
    userId: uuid.UUID
    systemRoles: List[RoleInfo]
    permissions: List[str]  # Permission strings in format "target:action:scope"
    isSuperAdmin: bool


class ResourcePermissionsResponse(BaseModel):
    """
    Response for resource-specific permissions endpoint.
    
    Contains permissions from resource roles only.
    """
    resourceRole: Optional[RoleInfo] = None
    permissions: List[str]  # Permission strings in format "target:action:scope"
    isOwner: bool
