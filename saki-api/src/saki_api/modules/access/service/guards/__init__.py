"""
Guards - Permission and authorization guards for FastAPI.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.session import get_session
from saki_api.modules.access.service.guards.admin_guard import AdminGuard


def get_admin_guard(
        session: AsyncSession = Depends(get_session),
) -> AdminGuard:
    """Get AdminGuard with dependencies injected."""
    return AdminGuard(session=session)


# Type alias for cleaner route signatures
AdminGuardDep = Annotated[AdminGuard, Depends(get_admin_guard)]

__all__ = ["AdminGuard", "AdminGuardDep", "get_admin_guard"]
