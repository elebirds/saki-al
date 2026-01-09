"""
Permission Checker Service

Provides efficient permission checking with support for:
- System roles and resource roles
- Permission inheritance
- Scope-based access control (all, owned, assigned, self)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set, Callable, Any, Union

from sqlmodel import Session, select

from saki_api.models.rbac import (
    Role, RoleType, RolePermission,
    UserSystemRole, ResourceMember, ResourceType, Scope,
)


@dataclass
class PermissionContext:
    """
    Context for permission checking.
    
    Provides all necessary information to evaluate a permission.
    """
    user_id: str
    resource_type: Optional[Union[ResourceType, str]] = None
    resource_id: Optional[str] = None
    resource_owner_id: Optional[str] = None  # Owner of the resource (for owned scope)
    target_creator_id: Optional[str] = None  # Creator of the target item (for self scope)


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
        """Check if user is a super admin."""
        permissions = self.get_user_system_permissions(user_id)
        return "*:*:all" in permissions
    
    def check(
        self,
        user_id: str,
        permission: str,
        resource_type: Optional[Union[ResourceType, str]] = None,
        resource_id: Optional[str] = None,
        resource_owner_id: Optional[str] = None,
        target_creator_id: Optional[str] = None,
    ) -> bool:
        """
        Check if a user has the required permission.
        
        Args:
            user_id: ID of the user
            permission: Permission string (resource:action or resource:action:scope)
            resource_type: Type of resource (optional, for resource-level permissions)
            resource_id: ID of the resource (optional)
            resource_owner_id: Owner of the resource (optional, for owned scope)
            target_creator_id: Creator of the target item (optional, for self scope)
        
        Returns:
            True if permission is granted, False otherwise
        
        Examples:
            # Check if user can read datasets (system level)
            checker.check(user_id, "dataset:read")
            
            # Check if user can update a specific dataset
            checker.check(user_id, "dataset:update", "dataset", dataset_id, dataset.owner_id)
            
            # Check if user can update their own annotation
            checker.check(user_id, "annotation:update:self", "dataset", dataset_id, 
                          target_creator_id=annotation.annotator_id)
        """
        ctx = PermissionContext(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_owner_id=resource_owner_id,
            target_creator_id=target_creator_id,
        )
        
        permissions = self._get_effective_permissions(ctx)
        
        # Super admin wildcard
        if "*:*:all" in permissions:
            return True
        
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
            if perm_resource != req_resource:
                continue
            
            # Check action match (manage covers all actions)
            if perm_action != req_action and perm_action != "manage":
                continue
            
            # Check scope
            if self._scope_covers(perm_scope, req_scope, ctx):
                return True
        
        return False
    
    def _scope_covers(
        self,
        perm_scope: str,
        req_scope: str,
        ctx: PermissionContext
    ) -> bool:
        """
        Check if permission scope covers the required scope.
        
        Scope hierarchy: all > owned > assigned > self
        """
        # 'all' covers everything
        if perm_scope == "all":
            return True
        
        # 'owned' covers owned resources
        if perm_scope == "owned":
            if req_scope in ["owned", "assigned", "self"]:
                # Check if user owns the resource
                if ctx.resource_owner_id and ctx.resource_owner_id == ctx.user_id:
                    return True
            return False
        
        # 'assigned' covers assigned resources and self
        if perm_scope == "assigned":
            if req_scope == "assigned":
                return True
            if req_scope == "self":
                # 'assigned' implicitly covers 'self' - user can access their own items
                if ctx.target_creator_id and ctx.target_creator_id == ctx.user_id:
                    return True
                # If no target_creator_id specified, assume assigned covers it
                if not ctx.target_creator_id:
                    return True
            return False
        
        # 'self' only covers self
        if perm_scope == "self":
            if req_scope == "self":
                if ctx.target_creator_id and ctx.target_creator_id == ctx.user_id:
                    return True
                # If no target_creator_id, we can't verify - deny by default
                return False
            return False
        
        return False
    
    def filter_accessible_resources(
        self,
        user_id: str,
        resource_type: Union[ResourceType, str],
        required_permission: str,
        base_query,
        get_owner_id_column: Callable[[], Any]
    ):
        """
        Filter a query to only include resources the user can access.
        
        Args:
            user_id: The user ID
            resource_type: Type of resource being queried
            required_permission: Permission required (e.g., "dataset:read")
            base_query: The base SQLAlchemy query
            get_owner_id_column: Function that returns the owner_id column
        
        Returns:
            Modified query with access filters applied
        
        Example:
            query = select(Dataset)
            filtered = checker.filter_accessible_resources(
                user_id=current_user.id,
                resource_type="dataset",
                required_permission="dataset:read",
                base_query=query,
                get_owner_id_column=lambda: Dataset.owner_id
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
        if "*:*:all" in system_perms:
            return base_query
        
        req_resource = required_permission.split(":")[0]
        req_action = required_permission.split(":")[1] if ":" in required_permission else "read"
        
        for perm in system_perms:
            parts = perm.split(":")
            if len(parts) >= 3:
                if (parts[0] == req_resource and
                    (parts[1] == req_action or parts[1] == "manage") and
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
                    (parts[1] == req_action or parts[1] == "manage") and
                    parts[2] == "owned"):
                    has_owned = True
                    break
        
        if has_owned:
            # Get resources owned by user
            from saki_api.models import Dataset
            if resource_type == ResourceType.DATASET:
                owned = self.session.exec(
                    select(Dataset.id).where(Dataset.owner_id == user_id)
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
        
        # Apply filter
        owner_col = get_owner_id_column()
        from saki_api.models import Dataset
        if resource_type == ResourceType.DATASET:
            return base_query.where(Dataset.id.in_(accessible_ids))
        
        return base_query
    
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
