"""
RBAC Enumerations

Defines the core enums for the permission system.
"""

from enum import Enum


class RoleType(str, Enum):
    """
    Role type - determines where the role applies.
    
    - SYSTEM: Global roles that apply system-wide
    - RESOURCE: Roles that apply to specific resources (datasets, projects, etc.)
    """
    SYSTEM = "system"
    RESOURCE = "resource"


class ResourceType(str, Enum):
    """
    Resource types that can have members.
    
    Add new resource types here to extend the permission system.
    """
    DATASET = "dataset"
    PROJECT = "project"  # Reserved for future use


class Scope(str, Enum):
    """
    Permission scope - defines the extent of a permission.
    
    Coverage hierarchy: all > owned > assigned > self
    
    - ALL: Access to all resources of this type (admin level)
    - OWNED: Access to resources created/owned by the user
    - ASSIGNED: Access to all items within assigned resources (member level)
    - SELF: Access only to items created by the user within assigned resources
    """
    ALL = "all"
    OWNED = "owned"
    ASSIGNED = "assigned"
    SELF = "self"


class AuditAction(str, Enum):
    """
    Audit log action types.
    """
    # Role management
    ROLE_CREATE = "role.create"
    ROLE_UPDATE = "role.update"
    ROLE_DELETE = "role.delete"
    
    # User role management
    USER_ROLE_ASSIGN = "user_role.assign"
    USER_ROLE_REVOKE = "user_role.revoke"
    
    # Resource member management
    MEMBER_ADD = "member.add"
    MEMBER_UPDATE = "member.update"
    MEMBER_REMOVE = "member.remove"
    
    # Permission events (for security auditing)
    PERMISSION_DENIED = "permission.denied"
    PERMISSION_GRANTED = "permission.granted"


# ============================================================================
# Permission Constants
# ============================================================================

class Resource(str, Enum):
    """
    Resource identifiers for permission strings.
    """
    SYSTEM = "system"
    USER = "user"
    ROLE = "role"
    AUDIT_LOG = "audit_log"
    DATASET = "dataset"
    SAMPLE = "sample"
    ANNOTATION = "annotation"
    LABEL = "label"
    PROJECT = "project"


class Action(str, Enum):
    """
    Action identifiers for permission strings.
    """
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    MANAGE = "manage"  # Includes all CRUD operations
    EXPORT = "export"
    IMPORT = "import"
    REVIEW = "review"
    ASSIGN = "assign"  # For member management


# Helper to build permission strings
def build_permission(resource: str, action: str, scope: str = "assigned") -> str:
    """Build a permission string in the format resource:action:scope"""
    return f"{resource}:{action}:{scope}"


# ============================================================================
# Predefined Permission Constants (for convenience)
# ============================================================================

class Permissions:
    """
    Predefined permission constants for common use cases.
    """
    # System
    SYSTEM_MANAGE = "system:manage:all"
    
    # User management
    USER_CREATE = "user:create:all"
    USER_READ = "user:read:all"
    USER_UPDATE = "user:update:all"
    USER_DELETE = "user:delete:all"
    USER_MANAGE = "user:manage:all"
    
    # Role management
    ROLE_CREATE = "role:create:all"
    ROLE_READ = "role:read:all"
    ROLE_UPDATE = "role:update:all"
    ROLE_DELETE = "role:delete:all"
    
    # Dataset - global scope
    DATASET_CREATE = "dataset:create:all"
    DATASET_READ_ALL = "dataset:read:all"
    DATASET_UPDATE_ALL = "dataset:update:all"
    DATASET_DELETE_ALL = "dataset:delete:all"
    
    # Dataset - owned scope
    DATASET_READ_OWNED = "dataset:read:owned"
    DATASET_UPDATE_OWNED = "dataset:update:owned"
    DATASET_DELETE_OWNED = "dataset:delete:owned"
    DATASET_ASSIGN_OWNED = "dataset:assign:owned"
    DATASET_EXPORT_OWNED = "dataset:export:owned"
    DATASET_IMPORT_OWNED = "dataset:import:owned"
    
    # Dataset - assigned scope (resource member level)
    DATASET_READ = "dataset:read:assigned"
    DATASET_UPDATE = "dataset:update:assigned"
    DATASET_DELETE = "dataset:delete:assigned"
    DATASET_ASSIGN = "dataset:assign:assigned"
    DATASET_EXPORT = "dataset:export:assigned"
    DATASET_IMPORT = "dataset:import:assigned"
    
    # Sample
    SAMPLE_READ = "sample:read:assigned"
    SAMPLE_CREATE = "sample:create:assigned"
    SAMPLE_UPDATE = "sample:update:assigned"
    SAMPLE_DELETE = "sample:delete:assigned"
    SAMPLE_MANAGE = "sample:manage:assigned"
    
    # Label
    LABEL_READ = "label:read:assigned"
    LABEL_MANAGE = "label:manage:assigned"
    
    # Annotation - assigned scope (can access all within dataset)
    ANNOTATION_READ = "annotation:read:assigned"
    ANNOTATION_CREATE = "annotation:create:assigned"
    ANNOTATION_UPDATE = "annotation:update:assigned"
    ANNOTATION_DELETE = "annotation:delete:assigned"
    ANNOTATION_REVIEW = "annotation:review:assigned"
    ANNOTATION_MANAGE = "annotation:manage:assigned"
    
    # Annotation - self scope (can only access own annotations)
    ANNOTATION_READ_SELF = "annotation:read:self"
    ANNOTATION_UPDATE_SELF = "annotation:update:self"
    ANNOTATION_DELETE_SELF = "annotation:delete:self"
