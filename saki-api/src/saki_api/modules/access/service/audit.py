"""
Audit Logging for RBAC

Provides functions to log permission-related events.
"""
import uuid
from typing import Optional, Union

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.access.domain.rbac import AuditLog, AuditAction


async def log_audit(
        session: AsyncSession,
        action: AuditAction,
        target_type: str,
        target_id: Union[str, uuid.UUID],
        old_value: Optional[dict] = None,
        new_value: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
) -> AuditLog:
    """
    Log an audit event.

    Args:
        session: Database session (sync or async)
        action: Type of action being logged
        target_type: Type of target (user, role, resource_member, etc.)
        target_id: ID of the target
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
            new_value={"name": role.name, "permissions": [...]},
        )
    """
    # Convert target_id to UUID if it's a string
    if isinstance(target_id, str):
        try:
            target_id = uuid.UUID(target_id)
        except ValueError:
            pass  # Keep as string if invalid UUID

    log_data = {
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "old_value": old_value,
        "new_value": new_value,
        "ip_address": ip_address,
        "user_agent": user_agent,
    }

    audit_repo = BaseRepository(AuditLog, session)
    return await audit_repo.create(log_data)


async def log_role_create(
        session: AsyncSession,
        role_id: uuid.UUID,
        role_data: dict,
        **kwargs
) -> AuditLog:
    """Log a role creation event."""
    return await log_audit(
        session=session,
        action=AuditAction.ROLE_CREATE,
        target_type="role",
        target_id=role_id,
        new_value=role_data,
        **kwargs
    )


async def log_role_update(
        session: AsyncSession,
        role_id: uuid.UUID,
        old_data: dict,
        new_data: dict,
        **kwargs
) -> AuditLog:
    """Log a role update event."""
    return await log_audit(
        session=session,
        action=AuditAction.ROLE_UPDATE,
        target_type="role",
        target_id=role_id,
        old_value=old_data,
        new_value=new_data,
        **kwargs
    )


async def log_role_delete(
        session: AsyncSession,
        role_id: uuid.UUID,
        role_data: dict,
        **kwargs
) -> AuditLog:
    """Log a role deletion event."""
    return await log_audit(
        session=session,
        action=AuditAction.ROLE_DELETE,
        target_type="role",
        target_id=role_id,
        old_value=role_data,
        **kwargs
    )


async def log_user_role_assign(
        session: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a user role assignment event."""
    return await log_audit(
        session=session,
        action=AuditAction.USER_ROLE_ASSIGN,
        target_type="user",
        target_id=user_id,
        new_value={"role_id": str(role_id)},
        **kwargs
    )


async def log_user_role_revoke(
        session: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a user role revocation event."""
    return await log_audit(
        session=session,
        action=AuditAction.USER_ROLE_REVOKE,
        target_type="user",
        target_id=user_id,
        old_value={"role_id": str(role_id)},
        **kwargs
    )


async def log_member_add(
        session: AsyncSession,
        resource_type: str,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member addition event."""
    return await log_audit(
        session=session,
        action=AuditAction.MEMBER_ADD,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        new_value={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "role_id": role_id,
        },
        **kwargs
    )


async def log_member_update(
        session: AsyncSession,
        resource_type: str,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        old_role_id: uuid.UUID,
        new_role_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member role update event."""
    return await log_audit(
        session=session,
        action=AuditAction.MEMBER_UPDATE,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        old_value={"role_id": str(old_role_id)},
        new_value={"role_id": str(new_role_id)},
        **kwargs
    )


async def log_member_remove(
        session: AsyncSession,
        resource_type: str,
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        **kwargs
) -> AuditLog:
    """Log a member removal event."""
    return await log_audit(
        session=session,
        action=AuditAction.MEMBER_REMOVE,
        target_type="resource_member",
        target_id=f"{resource_type}:{resource_id}:{user_id}",
        old_value={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "role_id": role_id,
        },
        **kwargs
    )


async def log_permission_denied(
        session: AsyncSession,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs
) -> AuditLog:
    """Log a permission denied event (for security auditing)."""
    return await log_audit(
        session=session,
        action=AuditAction.PERMISSION_DENIED,
        target_type="permission_check",
        target_id=permission,
        new_value={
            "permission": permission,
            "resource_type": resource_type,
            "resource_id": resource_id,
        },
        **kwargs
    )
