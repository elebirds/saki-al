"""
Permission Checker Service

Provides efficient permission checking with support for:
- System roles and resource roles
- Permission inheritance
- Scope-based access control (all, owned, assigned, self)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Callable, Any, Union

from saki_api.models.rbac.enums import Permissions
from sqlmodel import Session, select

from saki_api.models.rbac import (
    Role, RolePermission,
    UserSystemRole, ResourceMember, ResourceType, )


@dataclass
class PermissionContext:
    """
    Context for permission checking.
    
    Provides necessary information to evaluate a permission at the resource level.
    Note: Object-level access checks (e.g., is this annotation mine?) should be
    done in the business layer, not here.
    """
    user_id: str
    resource_type: Optional[Union[ResourceType, str]] = None
    resource_id: Optional[str] = None


class PermissionChecker:
    """
    Permission checking service.
    
    Provides efficient permission checking with caching support.
    
    Usage:
        checker = PermissionChecker(session)
        
        # Check a simple permission
        if checker.check(user_id, "dataset:read"):
            ...
        
        # Check with resource context
        if checker.check(user_id, "dataset:update", "dataset", dataset_id, dataset.owner_id):
            ...
    """

    def __init__(self, session: Session):
        self.session = session
        self._role_cache: dict[str, Role] = {}
        self._permission_cache: dict[str, Set[str]] = {}

    def get_role(self, role_id: str) -> Optional[Role]:
        """Get a role by ID with caching."""
        if role_id not in self._role_cache:
            self._role_cache[role_id] = self.session.get(Role, role_id)
        return self._role_cache[role_id]

    def get_role_permissions(self, role_id: str) -> Set[str]:
        """
        Get all permissions for a role, including inherited permissions.
        
        Uses recursion to handle role inheritance.
        """
        if role_id in self._permission_cache:
            return self._permission_cache[role_id]

        role = self.get_role(role_id)
        if not role:
            return set()

        permissions: Set[str] = set()

        # Get direct permissions
        role_perms = self.session.exec(
            select(RolePermission).where(RolePermission.role_id == role_id)
        ).all()

        for rp in role_perms:
            permissions.add(rp.permission)

        # Get inherited permissions from parent
        if role.parent_id:
            parent_perms = self.get_role_permissions(role.parent_id)
            permissions.update(parent_perms)

        self._permission_cache[role_id] = permissions
        return permissions

    def get_user_system_permissions(self, user_id: str) -> Set[str]:
        """
        Get all system-level permissions for a user.
        
        Combines permissions from all assigned system roles.
        """
        permissions: Set[str] = set()

        # Get user's system roles (filter out expired)
        user_roles = self.session.exec(
            select(UserSystemRole).where(
                UserSystemRole.user_id == user_id,
                (UserSystemRole.expires_at == None) |
                (UserSystemRole.expires_at > datetime.utcnow())
            )
        ).all()

        for ur in user_roles:
            role_perms = self.get_role_permissions(ur.role_id)
            permissions.update(role_perms)

        return permissions

    def get_user_resource_permissions(
            self,
            user_id: str,
            resource_type: Union[ResourceType, str],
            resource_id: str
    ) -> Set[str]:
        """
        Get permissions for a user on a specific resource.
        """
        permissions: Set[str] = set()

        # Convert string to enum if needed
        if isinstance(resource_type, str):
            try:
                resource_type = ResourceType(resource_type)
            except ValueError:
                return permissions

        member = self.session.exec(
            select(ResourceMember).where(
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id,
                ResourceMember.user_id == user_id
            )
        ).first()

        if member:
            role_perms = self.get_role_permissions(member.role_id)
            permissions.update(role_perms)

        return permissions

    def _get_effective_permissions(self, ctx: PermissionContext) -> Set[str]:
        """
        Get all effective permissions for a user in a given context.
        
        Combines system permissions and resource permissions.
        """
        permissions: Set[str] = set()

        # System permissions
        system_perms = self.get_user_system_permissions(ctx.user_id)
        permissions.update(system_perms)

        # Resource permissions (if resource context provided)
        if ctx.resource_type and ctx.resource_id:
            resource_perms = self.get_user_resource_permissions(
                ctx.user_id, ctx.resource_type, ctx.resource_id
            )
            permissions.update(resource_perms)

        return permissions

    def get_effective_permissions(self, ctx: PermissionContext) -> Set[str]:
        """
        Public method to get all effective permissions for a user in a given context.
        
        Combines system permissions and resource permissions.
        """
        return self._get_effective_permissions(ctx)

    def is_super_admin(self, user_id: str) -> bool:
        """Check if user is a super admin by checking if they have super_admin role."""
        # Get user's system roles (filter out expired)
        user_roles = self.session.exec(
            select(UserSystemRole).where(
                UserSystemRole.user_id == user_id,
                (UserSystemRole.expires_at == None) |
                (UserSystemRole.expires_at > datetime.utcnow())
            )
        ).all()
        
        for ur in user_roles:
            role = self.get_role(ur.role_id)
            if role and role.is_super_admin:
                return True
        
        return False
    
    def is_admin(self, user_id: str) -> bool:
        """Check if user is an admin (including super admin) by checking roles."""
        # Get user's system roles (filter out expired)
        user_roles = self.session.exec(
            select(UserSystemRole).where(
                UserSystemRole.user_id == user_id,
                (UserSystemRole.expires_at == None) |
                (UserSystemRole.expires_at > datetime.utcnow())
            )
        ).all()
        
        for ur in user_roles:
            role = self.get_role(ur.role_id)
            if role and (role.is_admin or role.is_super_admin):
                return True
        
        return False

    def check(
            self,
            user_id: str,
            permission: str,
            resource_type: Optional[Union[ResourceType, str]] = None,
            resource_id: Optional[str] = None
    ) -> bool:
        """
        Check if a user has the required permission level.
        
        This method checks if the user has been granted a permission at a sufficient
        scope level. Object-level access checks (e.g., "is this annotation mine?")
        should be done separately in the business layer.
        
        Args:
            user_id: ID of the user
            permission: Permission string (resource:action or resource:action:scope)
            resource_type: Type of resource (optional, for resource-level permissions)
            resource_id: ID of the resource (optional)
            resource_owner_id: Owner of the resource (optional, for owned scope)
        
        Returns:
            True if permission is granted, False otherwise
        
        Examples:
            # Check if user can read datasets (system level)
            checker.check(user_id, "dataset:read")
            
            # Check if user can update a specific dataset
            checker.check(user_id, "dataset:update", "dataset", dataset_id, dataset.owner_id)
            
            # Check if user has self-level annotation permission
            # Note: This only checks if user has the permission level,
            # checking if a specific annotation belongs to the user is done in business layer
            checker.check(user_id, "annotation:read:self", "dataset", dataset_id)
        """
        if self.is_super_admin(user_id):
            return True

        ctx = PermissionContext(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        permissions = self._get_effective_permissions(ctx)

        # Parse required permission
        req_parts = permission.split(":")
        if len(req_parts) < 2:
            return False

        req_resource = req_parts[0]
        req_action = req_parts[1]
        req_scope = req_parts[2] if len(req_parts) > 2 else "assigned"

        for perm in permissions:
            perm_parts = perm.split(":")
            if len(perm_parts) < 2:
                continue

            perm_resource = perm_parts[0]
            perm_action = perm_parts[1]
            perm_scope = perm_parts[2] if len(perm_parts) > 2 else "assigned"

            # Check resource match
            if perm_resource != req_resource and perm_action != "*":
                continue

            # Check action match (manage covers all actions)
            if perm_action != req_action and perm_action != "*":
                continue

            # Check scope
            if self._scope_covers(perm_scope, req_scope):
                return True

        return False

    def _scope_covers(
            self,
            perm_scope: str,
            req_scope: str
    ) -> bool:
        """
        Check if permission scope covers the required scope.
        
        Scope hierarchy: all > owned > assigned > self
        
        This only checks scope levels, not object ownership.
        Object-level checks (e.g., "is this annotation mine?") should be
        done in the business layer after confirming the user has the scope.
        """
        # 'all' covers everything
        if perm_scope == "all":
            return True

        # 'assigned' covers assigned and self
        if perm_scope == "assigned":
            return req_scope in ("assigned", "self")

        # 'self' only covers self
        if perm_scope == "self":
            return req_scope == "self"

        return False

    def filter_accessible_resources(
            self,
            user_id: str,
            resource_type: Union[ResourceType, str],
            required_permission: str,
            base_query,
            get_owner_id_column: Callable[[], Any],
            resource_model: Any  # The SQLModel class (e.g., Dataset)
    ):
        """
        Filter a query to only include resources the user can access.
        
        Args:
            user_id: The user ID
            resource_type: Type of resource being queried
            required_permission: Permission required (e.g., "dataset:read")
            base_query: The base SQLAlchemy query
            get_owner_id_column: Function that returns the owner_id column
            resource_model: The SQLModel class for the resource (e.g., Dataset)
        
        Returns:
            Modified query with access filters applied
        
        Example:
            query = select(Dataset)
            filtered = checker.filter_accessible_resources(
                user_id=current_user.id,
                resource_type="dataset",
                required_permission="dataset:read",
                base_query=query,
                get_owner_id_column=lambda: Dataset.owner_id,
                resource_model=Dataset
            )
        """
        # Convert string to enum if needed
        if isinstance(resource_type, str):
            try:
                resource_type = ResourceType(resource_type)
            except ValueError:
                return base_query.where(False)

        # Get user's system permissions
        system_perms = self.get_user_system_permissions(user_id)

        # Super admin or has 'all' scope - return everything
        if Permissions.ALL_PERMISSIONS in system_perms:
            return base_query

        req_resource = required_permission.split(":")[0]
        req_action = required_permission.split(":")[1] if ":" in required_permission else "*"

        for perm in system_perms:
            parts = perm.split(":")
            if len(parts) >= 3:
                if (parts[0] == req_resource and
                        (parts[1] == req_action or parts[1] == "*") and
                        parts[2] == "all"):
                    return base_query

        # Collect accessible resource IDs
        accessible_ids: Set[str] = set()

        # Check for 'owned' scope
        has_owned = False
        for perm in system_perms:
            parts = perm.split(":")
            if len(parts) >= 3:
                if (parts[0] == req_resource and
                        (parts[1] == req_action or parts[1] == "*") and
                        parts[2] == "owned"):
                    has_owned = True
                    break

        if has_owned:
            # Get resources owned by user using the provided owner_id column
            owner_id_col = get_owner_id_column()
            owned = self.session.exec(
                select(resource_model.id).where(owner_id_col == user_id)
            ).all()
            accessible_ids.update(owned)

        # Get resources where user is a member
        member_ids = self.session.exec(
            select(ResourceMember.resource_id).where(
                ResourceMember.resource_type == resource_type,
                ResourceMember.user_id == user_id
            )
        ).all()
        accessible_ids.update(member_ids)

        if not accessible_ids:
            # Return empty result
            return base_query.where(False)

        # Apply filter using the resource model's primary key
        return base_query.where(resource_model.id.in_(accessible_ids))

    def get_user_role_in_resource(
            self,
            user_id: str,
            resource_type: Union[ResourceType, str],
            resource_id: str
    ) -> Optional[Role]:
        """Get user's role in a specific resource."""
        # Convert string to enum if needed
        if isinstance(resource_type, str):
            try:
                resource_type = ResourceType(resource_type)
            except ValueError:
                return None

        member = self.session.exec(
            select(ResourceMember).where(
                ResourceMember.resource_type == resource_type,
                ResourceMember.resource_id == resource_id,
                ResourceMember.user_id == user_id
            )
        ).first()

        if member:
            return self.get_role(member.role_id)
        return None

    def clear_cache(self):
        """Clear permission cache."""
        self._role_cache.clear()
        self._permission_cache.clear()
