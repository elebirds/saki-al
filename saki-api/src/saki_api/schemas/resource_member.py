import uuid
from typing import Optional

from pydantic import BaseModel, Field, AliasPath

from saki_api.models.base import UUIDMixin
from saki_api.models.rbac.resource_member import ResourceMemberBase


# ============================================================================
# Resource Member Schemas
# ============================================================================

class ResourceMemberCreateRequest(BaseModel):
    """Schema for creating a resource member via HTTP request.
    
    Only includes user_id and role_id. The resource_type and resource_id
    are determined from the URL path, not the request body.
    """
    user_id: uuid.UUID
    role_id: uuid.UUID


class ResourceMemberUpdateRequest(BaseModel):
    """Schema for updating a resource member via HTTP request."""
    role_id: uuid.UUID


class ResourceMemberCreate(ResourceMemberBase):
    pass


class ResourceMemberRead(ResourceMemberBase, UUIDMixin):
    """Schema for reading a resource member."""

    user_email: Optional[str] = Field(None, validation_alias=AliasPath("user", "email"))
    user_full_name: Optional[str] = Field(None, validation_alias=AliasPath("user", "full_name"))
    user_avatar_url: Optional[str] = Field(None, validation_alias=AliasPath("user", "avatar_url"))

    role_name: Optional[str] = Field(None, validation_alias=AliasPath("role", "name"))
    role_display_name: Optional[str] = Field(None, validation_alias=AliasPath("role", "display_name"))
    role_color: Optional[str] = Field(None, validation_alias=AliasPath("role", "color"))
    role_is_supremo: Optional[bool] = Field(None, validation_alias=AliasPath("role", "is_supremo"))

    model_config = {"from_attributes": True}
