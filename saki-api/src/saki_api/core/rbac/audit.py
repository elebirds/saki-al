"""
Audit Logging for RBAC

Provides functions to log permission-related events.
"""
import uuid
from typing import Optional

from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac import AuditLog, AuditAction


def log_audit(
        session: Session | AsyncSession,
        action: AuditAction,
        target_type: str,
        target_id: str | uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
        old_value: Optional[dict] = None,
        new_value: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
) -> AuditLog:
    """
    Log an audit event.
    
    Args:
        session: Database session
        action: Type of action being logged
        target_type: Type of target (user, role, resource_member, etc.)
        target_id: ID of the target
        actor_id: ID of user performing the action
        old_value: Previous value (for updates)
        new_value: New value (for creates/updates)
        ip_address: Client IP address
        user_agent: Client user agent
    
    Returns:
        Created AuditLog entry
    
    Example:
        log_audit(
            session=session,
            action=AuditAction.ROLE_CREATE,
            target_type="role",
            target_id=role.id,
            actor_id=current_user.id,
            new_value={"name": role.name, "permissions": [...]},
        )
    """
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(log)
    # Don't commit here - let the caller manage the transaction
    return log


def log_role_create(
        session: Session | AsyncSession,
        role_id: str | uuid.UUID,
        role_data: dict,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a role creation event."""
    return log_audit(
        session=session,
        action=AuditAction.ROLE_CREATE,
        target_type="role",
        target_id=role_id,
        actor_id=actor_id,
        new_value=role_data,
        **kwargs
    )


def log_role_update(
        session: Session | AsyncSession,
        role_id: str | uuid.UUID,
        old_data: dict,
        new_data: dict,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a role update event."""
    return log_audit(
        session=session,
        action=AuditAction.ROLE_UPDATE,
        target_type="role",
        target_id=role_id,
        actor_id=actor_id,
        old_value=old_data,
        new_value=new_data,
        **kwargs
    )


def log_role_delete(
        session: Session | AsyncSession,
        role_id: str | uuid.UUID,
        role_data: dict,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a role deletion event."""
    return log_audit(
        session=session,
        action=AuditAction.ROLE_DELETE,
        target_type="role",
        target_id=role_id,
        actor_id=actor_id,
        old_value=role_data,
        **kwargs
    )


def log_user_role_assign(
        session: Session | AsyncSession,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a user role assignment event."""
    return log_audit(
        session=session,
        action=AuditAction.USER_ROLE_ASSIGN,
        target_type="user",
        target_id=user_id,
        actor_id=actor_id,
        new_value={"role_id": str(role_id)},
        **kwargs
    )


def log_user_role_revoke(
        session: Session | AsyncSession,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a user role revocation event."""
    return log_audit(
        session=session,
        action=AuditAction.USER_ROLE_REVOKE,
        target_type="user",
        target_id=user_id,
        actor_id=actor_id,
        old_value={"role_id": str(role_id)},
        **kwargs
    )


def log_member_add(
        session: Session,
        resource_type: str,
        resource_id: str,
        user_id: str,
        role_id: str,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member addition event."""
    return log_audit(
        session=session,
        action=AuditAction.MEMBER_ADD,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        actor_id=actor_id,
        new_value={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "role_id": role_id,
        },
        **kwargs
    )


def log_member_update(
        session: Session,
        resource_type: str,
        resource_id: str,
        user_id: str,
        old_role_id: str,
        new_role_id: str,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member role update event."""
    return log_audit(
        session=session,
        action=AuditAction.MEMBER_UPDATE,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        actor_id=actor_id,
        old_value={"role_id": str(old_role_id)},
        new_value={"role_id": str(new_role_id)},
        **kwargs
    )


def log_member_remove(
        session: Session,
        resource_type: str,
        resource_id: str,
        user_id: str,
        role_id: str,
        actor_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member removal event."""
    return log_audit(
        session=session,
        action=AuditAction.MEMBER_REMOVE,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        actor_id=actor_id,
        old_value={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "role_id": role_id,
        },
        **kwargs
    )


def log_permission_denied(
        session: Session,
        user_id: uuid.UUID,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs
) -> AuditLog:
    """Log a permission denied event (for security auditing)."""
    return log_audit(
        session=session,
        action=AuditAction.PERMISSION_DENIED,
        target_type="permission_check",
        target_id=permission,
        actor_id=user_id,
        new_value={
            "permission": permission,
            "resource_type": resource_type,
            "resource_id": resource_id,
        },
        **kwargs
    )
