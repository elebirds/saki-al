"""
Permission Model

Represents a permission with target, action, and scope.
Supports automatic conversion from permission strings.
"""
from dataclasses import dataclass
from typing import Set, Union

from saki_api.models.rbac.enums import VALID_SCOPE_STRS


@dataclass(frozen=True)
class Permission:
    """
    Represents a permission with target, action, and scope.
    
    Format: target:action:scope
    Example: "dataset:read:all"
    
    Attributes:
        target: Target type (e.g., "dataset", "user", "*" for all)
        action: Action type (e.g., "read", "create", "*" for all)
        scope: Permission scope (e.g., "all", "assigned", "self")
    """
    target: str
    action: str
    scope: str = "assigned"  # Default scope

    def __str__(self) -> str:
        """Convert permission to string format."""
        return f"{self.target}:{self.action}:{self.scope}"

    def __repr__(self) -> str:
        """Representation for debugging."""
        return f"Permission(target={self.target!r}, action={self.action!r}, scope={self.scope!r})"

    def __eq__(self, other: object) -> bool:
        """Check if two permissions are equal."""
        if not isinstance(other, Permission):
            return False
        return (
                self.target == other.target and
                self.action == other.action and
                self.scope == other.scope
        )

    def __hash__(self) -> int:
        """Make Permission hashable (required for use in sets/dicts)."""
        return hash((self.target, self.action, self.scope))

    def __le__(self, other: Union["Permission", str]) -> bool:
        """
        Check if this permission is covered by (less than or equal to) another permission.
        
        Usage: required <= user_perm  (check if user_perm covers required)
        
        Examples:
            >>> required = Permission.from_string("dataset:read:assigned")
            >>> user_perm = Permission.from_string("dataset:read:all")
            >>> required <= user_perm
            True  # user_perm covers required
        """
        if isinstance(other, str):
            other = Permission.from_string(other)
        return other.covers(self)

    def __ge__(self, other: Union["Permission", str]) -> bool:
        """
        Check if this permission covers (greater than or equal to) another permission.
        
        Usage: user_perm >= required  (check if user_perm covers required)
        
        Examples:
            >>> user_perm = Permission.from_string("dataset:read:all")
            >>> required = Permission.from_string("dataset:read:assigned")
            >>> user_perm >= required
            True  # user_perm covers required
        """
        if isinstance(other, str):
            other = Permission.from_string(other)
        return self.covers(other)

    def __lt__(self, other: Union["Permission", str]) -> bool:
        """
        Check if this permission is strictly less than (covered by) another permission.
        
        Usage: required < user_perm  (check if user_perm strictly covers required)
        
        Note: This checks if other covers self AND they are not equal.
        """
        if isinstance(other, str):
            other = Permission.from_string(other)
        return other.covers(self) and self != other

    def __gt__(self, other: Union["Permission", str]) -> bool:
        """
        Check if this permission is strictly greater than (strictly covers) another permission.
        
        Usage: user_perm > required  (check if user_perm strictly covers required)
        
        Note: This checks if self covers other AND they are not equal.
        """
        if isinstance(other, str):
            other = Permission.from_string(other)
        return self.covers(other) and self != other

    @classmethod
    def from_string(cls, permission_str: str) -> "Permission":
        """
        Create a Permission object from a permission string.
        
        Args:
            permission_str: Permission string in format "target:action:scope" or "target:action"
            
        Returns:
            Permission object
            
        Raises:
            ValueError: If the permission string format is invalid
            
        Examples:
            >>> Permission.from_string("dataset:read:all")
            Permission(target='dataset', action='read', scope='all')
            >>> Permission.from_string("dataset:read")
            Permission(target='dataset', action='read', scope='assigned')
        """
        parts = permission_str.split(":")

        if len(parts) < 2:
            raise ValueError(
                f"Invalid permission format: {permission_str}. "
                f"Expected format: 'target:action:scope' or 'target:action'"
            )

        target = parts[0]
        action = parts[1]
        scope = parts[2] if len(parts) > 2 else "assigned"

        # Validate scope if provided
        if scope not in VALID_SCOPE_STRS:
            raise ValueError(
                f"Invalid scope: {scope}. Valid scopes are: {', '.join(VALID_SCOPE_STRS)}"
            )

        return cls(target=target, action=action, scope=scope)

    def matches(self, other: "Permission", allow_wildcards: bool = True) -> bool:
        """
        Check if this permission matches another permission.
        
        Supports wildcard matching:
        - "*" matches any target/action
        - Scope hierarchy: all > assigned > self
        
        Args:
            other: Permission to match against
            allow_wildcards: Whether to allow wildcard matching
            
        Returns:
            True if permissions match
            
        Examples:
            >>> p1 = Permission.from_string("dataset:read:all")
            >>> p2 = Permission.from_string("dataset:read:assigned")
            >>> p1.matches(p2)
            True  # all scope covers assigned
            
            >>> p1 = Permission.from_string("*:read:all")
            >>> p2 = Permission.from_string("dataset:read:all")
            >>> p1.matches(p2)
            True  # wildcard matches
        """
        # Check target match
        if self.target != other.target:
            if not allow_wildcards:
                return False
            if self.target != "*" and other.target != "*":
                return False

        # Check action match
        if self.action != other.action:
            if not allow_wildcards:
                return False
            if self.action != "*" and other.action != "*":
                return False

        # Check scope - higher scope covers lower scope
        return self._scope_covers(self.scope, other.scope)

    @staticmethod
    def _scope_covers(have_scope: str, req_scope: str) -> bool:
        """
        Check if the scope we have covers the required scope.
        
        Scope hierarchy: all > assigned > self
        
        Args:
            have_scope: The scope we have
            req_scope: The required scope
            
        Returns:
            True if have_scope covers req_scope
        """
        scope_hierarchy = {
            "all": 3,
            "assigned": 2,
            "self": 1,
        }

        have_level = scope_hierarchy.get(have_scope, 0)
        req_level = scope_hierarchy.get(req_scope, 0)

        return have_level >= req_level

    def is_satisfied_by(self, permission_set: Set[str]) -> bool:
        """
        Check if this permission requirement is satisfied by any permission in the set.
        
        This method checks if any permission in the given set covers this permission,
        considering wildcards and scope hierarchy.
        
        Args:
            permission_set: Set of permission strings (e.g., {"dataset:read:all", "user:create:all"})
            
        Returns:
            True if this permission is satisfied by the set
            
        Examples:
            >>> required = Permission.from_string("dataset:read:assigned")
            >>> permissions = {"dataset:read:all", "user:create:all"}
            >>> required.is_satisfied_by(permissions)
            True  # "dataset:read:all" covers "dataset:read:assigned"
            
            >>> required = Permission.from_string("dataset:write:assigned")
            >>> permissions = {"dataset:read:all"}
            >>> required.is_satisfied_by(permissions)
            False  # read doesn't cover write
        """
        for perm_str in permission_set:
            try:
                perm = self.from_string(perm_str)
                # Check if the permission in set covers this requirement
                if perm.covers(self):
                    return True
            except ValueError:
                # Skip invalid permission strings
                continue
        return False

    def check_in(self, permission_set: Set[str]) -> bool:
        """
        Alias for is_satisfied_by() - more intuitive name for checking.
        
        Args:
            permission_set: Set of permission strings
            
        Returns:
            True if this permission is satisfied by the set
        """
        return self.is_satisfied_by(permission_set)

    @staticmethod
    def check_permission(
            required: Union["Permission", str],
            available: Set[str]
    ) -> bool:
        """
        Static method to check if a required permission is satisfied by available permissions.
        
        This is a convenience method that handles both Permission objects and strings.
        
        Args:
            required: Required permission (Permission object or string)
            available: Set of available permission strings
            
        Returns:
            True if required permission is satisfied
            
        Examples:
            >>> Permission.check_permission("dataset:read:assigned", {"dataset:read:all"})
            True
            
            >>> perm = Permission.from_string("dataset:read:assigned")
            >>> Permission.check_permission(perm, {"dataset:read:all"})
            True
        """
        if isinstance(required, str):
            required = Permission.from_string(required)
        return required.is_satisfied_by(available)

    def covers(self, other: Union["Permission", str]) -> bool:
        """
        Check if this permission covers another permission.
        
        This is similar to matches(), but checks if THIS permission covers the OTHER,
        which is useful when checking if a user's permission covers a required permission.
        
        Args:
            other: Permission to check against (Permission object or string)
            
        Returns:
            True if this permission covers the other
            
        Examples:
            >>> user_perm = Permission.from_string("dataset:read:all")
            >>> required = Permission.from_string("dataset:read:assigned")
            >>> user_perm.covers(required)
            True  # all scope covers assigned
            
            >>> user_perm = Permission.from_string("dataset:*:all")
            >>> required = Permission.from_string("dataset:write:assigned")
            >>> user_perm.covers(required)
            True  # wildcard action and all scope covers write:assigned
        """
        if isinstance(other, str):
            other = Permission.from_string(other)

        # Check target match (with wildcard support)
        if self.target != other.target:
            if self.target != "*" and other.target != "*":
                return False

        # Check action match (with wildcard support)
        if self.action != other.action:
            if self.action != "*" and other.action != "*":
                return False

        # Check scope - this permission's scope must cover the required scope
        return self._scope_covers(self.scope, other.scope)

    def with_scope(self, scope: str) -> "Permission":
        """
        Create a new Permission with the same target and action but different scope.
        
        Useful for checking different scope levels of the same permission.
        
        Args:
            scope: New scope value
            
        Returns:
            New Permission object with updated scope
            
        Examples:
            >>> perm = Permission.from_string("dataset:read:assigned")
            >>> all_perm = perm.with_scope("all")
            >>> print(all_perm)
            "dataset:read:all"
        """
        return Permission(target=self.target, action=self.action, scope=scope)

    def to_dict(self) -> dict:
        """Convert permission to dictionary."""
        return {
            "target": self.target,
            "action": self.action,
            "scope": self.scope,
            "permission": str(self),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Permission":
        """Create Permission from dictionary."""
        if "permission" in data:
            return cls.from_string(data["permission"])
        if "target" not in data:
            raise ValueError("Dictionary must contain 'target' key")
        return cls(
            target=data["target"],
            action=data["action"],
            scope=data.get("scope", "assigned"),
        )


def parse_permission(permission_str: str) -> Permission:
    """
    Convenience function to parse a permission string.
    
    Args:
        permission_str: Permission string in format "target:action:scope" or "target:action"
        
    Returns:
        Permission object
        
    Examples:
        >>> parse_permission("dataset:read:all")
        Permission(target='dataset', action='read', scope='all')
    """
    return Permission.from_string(permission_str)
