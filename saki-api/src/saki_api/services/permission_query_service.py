"""
Permission Query Service - Aggregate permission view for the current user.
"""

import uuid
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.rbac import PermissionChecker, PermissionContext
from saki_api.models import Role, User
from saki_api.models.rbac.enums import ResourceType
from saki_api.repositories.role_repository import RoleRepository
from saki_api.repositories.user_repository import UserRepository


class PermissionQueryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.role_repo = RoleRepository(session)

    async def get_my_permissions(
            self,
            current_user: User,
            checker: PermissionChecker,
            resource_type: Optional[str] = None,
            resource_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        # System roles
        user_roles = await self.user_repo.get_user_system_roles(current_user.id)
        system_roles: List[Dict[str, Any]] = []
        for ur in user_roles:
            role: Optional[Role] = await self.role_repo.get_by_id(ur.role_id)
            if role:
                system_roles.append({
                    "id": role.id,
                    "name": role.name,
                    "displayName": role.display_name,
                })

        # Super admin check
        is_super_admin = await checker.is_super_admin(current_user.id)

        # Permission context
        ctx = PermissionContext(user_id=current_user.id)
        if resource_type and resource_id:
            try:
                rt = ResourceType(resource_type)
                ctx = PermissionContext(
                    user_id=current_user.id,
                    resource_type=rt,
                    resource_id=resource_id,
                )
            except ValueError:
                pass

        permissions = await checker.get_effective_permissions(ctx)

        # Resource role and owner flag
        resource_role = None
        is_owner = None
        if resource_type and resource_id:
            try:
                rt = ResourceType(resource_type)
                role = await checker.get_user_role_in_resource(current_user.id, rt, resource_id)
                if role:
                    resource_role = {
                        "id": role.id,
                        "name": role.name,
                        "displayName": role.display_name,
                    }

                if resource_type == "dataset":
                    from saki_api.models import Dataset
                    dataset = await self.session.get(Dataset, resource_id)
                    if dataset:
                        is_owner = (dataset.owner_id == current_user.id)
            except ValueError:
                pass

        return {
            "userId": current_user.id,
            "systemRoles": system_roles,
            "resourceRole": resource_role,
            "permissions": list(permissions),
            "isSuperAdmin": is_super_admin,
            "isOwner": is_owner,
        }
