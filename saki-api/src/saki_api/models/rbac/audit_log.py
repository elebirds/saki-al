"""
Audit log model for permission system.

Records all permission-related changes for security auditing.
"""

import uuid
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from saki_api.models.base import UUIDMixin, TimestampMixin, AuditMixin
from saki_api.models.rbac.enums import AuditAction


class AuditLogBase(SQLModel):
    # Action
    action: AuditAction = Field(
        index=True,
        description="Type of action"
    )

    # Target
    target_type: str = Field(
        max_length=50,
        description="Type of target (user, role, resource_member, etc.)"
    )
    target_id: uuid.UUID = Field(
        max_length=100,
        description="ID of the target"
    )

    # Change details
    old_value: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Previous value (for updates)"
    )
    new_value: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON),
        description="New value (for creates/updates)"
    )

    # Context
    ip_address: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Client IP address"
    )
    user_agent: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Client user agent"
    )


class AuditLog(AuditLogBase, UUIDMixin, TimestampMixin, AuditMixin, table=True):
    """
    Permission Audit Log.
    
    Records all permission-related operations for security auditing.
    """
    __tablename__ = "audit_log"
