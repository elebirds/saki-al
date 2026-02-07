"""
Permission Checker Service

Provides efficient permission checking with support for:
- System roles and resource roles
- Permission inheritance
- Scope-based access control (all, owned, assigned, self)
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Callable, Any, Union

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac import (
    Role, ResourceType, Permission, parse_permission)
from saki_api.models.rbac.enums import Permissions
from saki_api.repositories.permission import PermissionRepository
from saki_api.repositories.resource_member import ResourceMemberRepository
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.user_system_role import UserSystemRoleRepository


@dataclass
class PermissionContext:
    """
    Context for permission checking.
    
    Provides necessary information to evaluate a permission at the resource level.
    Note: Object-level access checks (e.g., is this annotation mine?) should be
    done in the business layer, not here.
    """
    user_id: uuid.UUID
    resource_type: Optional[ResourceType] = None
    resource_id: Optional[uuid.UUID] = None


class PermissionChecker:
    """
    Permission checking service.
    
    Provides efficient permission checking with caching support.
    Uses Repository pattern - all database operations go through repositories.
    
    Usage:
        checker = PermissionChecker(session)
        
        # Check a simple permission
        if await checker.check(user_id, "dataset:read"):
            ...
        
        # Check with resource context
        if await checker.check(user_id, "dataset:update", "dataset", dataset_id):
            ...
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.role_repo = RoleRepository(session)
        self.permission_repo = PermissionRepository(session)
        self.user_role_repo = UserSystemRoleRepository(session)
        self.resource_member_repo = ResourceMemberRepository(session)
        self._role_cache: dict[uuid.UUID, Role] = {}
        self._permission_cache: dict[uuid.UUID, Set[str]] = {}

    async def get_user_system_permissions(self, user_id: uuid.UUID) -> Set[str]:
        """
        Efficiently get all system-level permissions for a user.
        
        Uses optimized SQL JOIN query to get all permissions in a single database call,
        avoiding the need to first fetch role IDs and then query permissions.
        """
        return await self.permission_repo.get_user_system_permissions(user_id, datetime.utcnow())

    async def get_user_resource_permissions(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            resource_id: uuid.UUID
    ) -> Set[str]:
        """
        Efficiently get permissions for a user on a specific resource.
        
        Uses optimized SQL JOIN query to get permissions in a single database call.
        
        Args:
            user_id: User ID
            resource_type: Resource type enum (must be ResourceType, not string)
            resource_id: Resource ID
        """
        # Use optimized SQL JOIN query through repository
        return await self.permission_repo.get_user_resource_permissions(
            user_id, resource_type, resource_id
        )

    async def _get_effective_permissions(self, ctx: PermissionContext) -> Set[str]:
        """
        Get all effective permissions for a user in a given context.
        
        Combines system permissions and resource permissions.
        """
        permissions: Set[str] = set()

        # System permissions
        system_perms = await self.get_user_system_permissions(ctx.user_id)
        permissions.update(system_perms)

        # Resource permissions (if resource context provided)
        if ctx.resource_type and ctx.resource_id:
            resource_perms = await self.get_user_resource_permissions(
                ctx.user_id, ctx.resource_type, ctx.resource_id
            )
            permissions.update(resource_perms)

        return permissions

    async def get_effective_permissions(self, ctx: PermissionContext) -> Set[str]:
        """
        Public method to get all effective permissions for a user in a given context.
        
        Combines system permissions and resource permissions.
        """
        return await self._get_effective_permissions(ctx)

    async def is_super_admin(self, user_id: uuid.UUID) -> bool:
        """
        Efficiently check if user is a super admin using optimized SQL query.
        
        Uses EXISTS query with JOIN to check role properties directly in database,
        avoiding the need to fetch all roles and check individually.
        """
        return await self.user_role_repo.has_super_admin_role(user_id, datetime.utcnow())

    async def is_admin(self, user_id: uuid.UUID) -> bool:
        """
        Efficiently check if user is an admin (including super admin) using optimized SQL query.
        
        Uses EXISTS query with JOIN to check role properties directly in database,
        avoiding the need to fetch all roles and check individually.
        """
        return await self.user_role_repo.has_admin_role(user_id, datetime.utcnow())

    async def check(
            self,
            user_id: uuid.UUID,
            permission: str | Permission,
            resource_type: Optional[ResourceType] = None,
            resource_id: Optional[str] = None
    ) -> bool:
        """
        Check if a user has the required permission level.
        
        This method checks if the user has been granted a permission at a sufficient
        scope level. Object-level access checks (e.g., "is this annotation mine?")
        should be done separately in the business layer.
        
        Args:
            user_id: ID of the user
            permission: Permission string (target:action or target:action:scope) or Permission object
            resource_type: Type of resource (optional, for resource-level permissions)
            resource_id: ID of the resource (optional)
        
        Returns:
            True if permission is granted, False otherwise
        
        Examples:
            # Check if user can read datasets (system level) - using string
            await checker.check(user_id, "dataset:read")
            
            # Check using Permission object
            from saki_api.models.rbac import parse_permission
            perm = parse_permission("dataset:read:all")
            await checker.check(user_id, perm)
            
            # Check if user can update a specific dataset
            await checker.check(user_id, "dataset:update", ResourceType.DATASET, dataset_id)
            
            # Check if user has self-level annotation permission
            # Note: This only checks if user has the permission level,
            # checking if a specific annotation belongs to the user is done in business layer
            await checker.check(user_id, "annotation:read:self", ResourceType.DATASET, dataset_id)
        """
        if await self.is_super_admin(user_id):
            return True

        # Convert to Permission object if needed
        if isinstance(permission, Permission):
            required_perm = permission
        else:
            try:
                required_perm = parse_permission(permission)
            except ValueError:
                return False  # Invalid permission format

        # Convert resource_id string to UUID if provided
        resource_id_uuid = None
        if resource_id:
            try:
                resource_id_uuid = uuid.UUID(resource_id)
            except ValueError:
                return False  # Invalid UUID format

        ctx = PermissionContext(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id_uuid,
        )

        permissions = await self._get_effective_permissions(ctx)

        # Use Permission class method to check if requirement is satisfied
        return required_perm.is_satisfied_by(permissions)

    async def filter_accessible_resources(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            required_permission: Union[str, Permission],
            base_query,
            get_owner_id_column: Callable[[], Any],
            resource_model: Any  # The SQLModel class (e.g., Dataset)
    ):
        """
        Filter a query to only include resources the user can access.
        
        Args:
            user_id: The user ID
            resource_type: Type of resource being queried (must be ResourceType enum)
            required_permission: Permission required (Permission object or string, e.g., "dataset:read")
            base_query: The base SQLAlchemy query
            get_owner_id_column: Function that returns the owner_id column
            resource_model: The SQLModel class for the resource (e.g., Dataset)
        
        Returns:
            Modified query with access filters applied
        
        Example:
            from saki_api.models.rbac import ResourceType, parse_permission
            
            query = select(Dataset)
            # Using string
            filtered = checker.filter_accessible_resources(
                user_id=current_user.id,
                resource_type=ResourceType.DATASET,
                required_permission="dataset:read",
                base_query=query,
                get_owner_id_column=lambda: Dataset.owner_id,
                resource_model=Dataset
            )
            # Using Permission object
            perm = parse_permission("dataset:read")
            filtered = checker.filter_accessible_resources(
                user_id=current_user.id,
                resource_type=ResourceType.DATASET,
                required_permission=perm,
                base_query=query,
                get_owner_id_column=lambda: Dataset.owner_id,
                resource_model=Dataset
            )
        """
        # Get user's system permissions
        system_perms = await self.get_user_system_permissions(user_id)

        # Convert to Permission object if needed
        if isinstance(required_permission, Permission):
            required_perm = required_permission
        else:
            try:
                required_perm = parse_permission(required_permission)
            except ValueError:
                return base_query.where(False)  # Invalid permission format

        # Super admin or has 'all' scope - return everything
        all_permissions_perm = parse_permission(Permissions.ALL_PERMISSIONS)
        if all_permissions_perm.is_satisfied_by(system_perms):
            return base_query

        # Check if user has 'all' scope for this permission using Permission.with_scope()
        if required_perm.with_scope("all").is_satisfied_by(system_perms):
            return base_query

        # Collect accessible resource IDs (as UUIDs)
        accessible_ids: Set[uuid.UUID] = set()

        # Check for 'owned' scope using Permission.with_scope()
        has_owned = required_perm.with_scope("owned").is_satisfied_by(system_perms)

        if has_owned:
            # Get resources owned by user using the provided owner_id column
            # Note: This is a dynamic query that works with any resource model.
            # Since it's model-agnostic, we keep it here rather than in a repository.
            # The owner_id column is provided by the caller, making this flexible.
            owner_id_col = get_owner_id_column()
            result = await self.session.exec(
                select(resource_model.id).where(owner_id_col == user_id)
            )
            owned = result.all()
            accessible_ids.update(owned)

        # Get resources where user is a member through repository
        member_ids = await self.resource_member_repo.get_resource_ids_by_user(
            user_id, resource_type
        )
        accessible_ids.update(member_ids)  # member_ids is List[uuid.UUID], compatible with Set[uuid.UUID]

        if not accessible_ids:
            # Return empty result
            return base_query.where(False)

        # Apply filter using the resource model's primary key
        return base_query.where(resource_model.id.in_(accessible_ids))

    async def get_user_role_in_resource(
            self,
            user_id: uuid.UUID,
            resource_type: ResourceType,
            resource_id: uuid.UUID
    ) -> Optional[Role]:
        """
        Efficiently get user's role in a specific resource.
        
        Uses optimized SQL JOIN query to get role directly in a single database call.
        
        Args:
            user_id: User ID
            resource_type: Resource type enum (must be ResourceType, not string)
            resource_id: Resource ID
        """
        # Use optimized SQL JOIN query through repository
        return await self.resource_member_repo.get_user_role_in_resource(
            user_id, resource_type, resource_id
        )

    def clear_cache(self):
        """Clear permission cache."""
        self._role_cache.clear()
        self._permission_cache.clear()
