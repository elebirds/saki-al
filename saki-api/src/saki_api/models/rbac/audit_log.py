"""
Audit log model for permission system.

Records all permission-related changes for security auditing.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from saki_api.models.rbac.enums import AuditAction


class AuditLog(SQLModel, table=True):
    """
    Permission Audit Log.
    
    Records all permission-related operations for security auditing.
    """
    __tablename__ = "audit_log"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        description="Unique identifier"
    )

    # Actor (who performed the action)
    actor_id: Optional[str] = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        description="User who performed the action"
    )

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
    target_id: str = Field(
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

    # Timestamp
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        index=True,
        description="When the action occurred"
    )


# ============================================================================
# Schema Models
# ============================================================================

class AuditLogRead(SQLModel):
    """Schema for reading an audit log entry."""
    id: str
    actor_id: Optional[str] = None
    action: AuditAction
    target_type: str
    target_id: str
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    # Actor details (joined)
    actor_email: Optional[str] = None
