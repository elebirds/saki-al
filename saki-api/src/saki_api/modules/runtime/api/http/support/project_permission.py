"""Project-level permission helper for runtime HTTP endpoints."""

from __future__ import annotations

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import ForbiddenAppException
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.access.domain.rbac import ResourceType


async def ensure_project_permission(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required_permission: str,
    fallback_permissions: tuple[str, ...] = (),
) -> None:
    checker = PermissionChecker(session)
    allowed = await checker.check(
        user_id=current_user_id,
        permission=required_permission,
        resource_type=ResourceType.PROJECT,
        resource_id=str(project_id),
    )
    if allowed:
        return

    for permission in fallback_permissions:
        allowed = await checker.check(
            user_id=current_user_id,
            permission=permission,
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
        )
        if allowed:
            return

    raise ForbiddenAppException(f"Permission denied: {required_permission}")
