"""
Permission Query Schemas

Schemas for permission query responses, separated into system and resource permissions.
"""

import uuid
from typing import List, Optional

from pydantic import BaseModel

from saki_api.schemas import RoleReadMinimal

class SystemPermissionsResponse(BaseModel):
    """
    Response for system-level permissions endpoint.
    
    Contains permissions from system roles only.
    """
    user_id: uuid.UUID
    system_roles: List[RoleReadMinimal]
    permissions: List[str]  # Permission strings in format "target:action:scope"
    is_super_admin: bool


class ResourcePermissionsResponse(BaseModel):
    """
    Response for resource-specific permissions endpoint.
    
    Contains permissions from resource roles only.
    """
    resource_role: Optional[RoleReadMinimal] = None
    permissions: List[str]  # Permission strings in format "target:action:scope"
    is_owner: bool
