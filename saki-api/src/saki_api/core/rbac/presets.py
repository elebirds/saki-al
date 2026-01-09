"""
Preset Role Configurations

Defines system preset roles that are created on system initialization.
These roles cannot be deleted.
"""

from typing import List, Dict, Any

from sqlmodel import Session, select

from saki_api.models.rbac import (
    Role, RoleType, RolePermission,
    Permissions,
)


# ============================================================================
# Preset Role Definitions
# ============================================================================

PRESET_ROLES: List[Dict[str, Any]] = [
    # ========================================================================
    # System Roles (Global Permissions)
    # ========================================================================
    {
        "name": "super_admin",
        "display_name": "超级管理员",
        "description": "拥有系统所有权限，不受任何限制",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": False,
        "sort_order": 0,
        "permissions": [
            "*:*:all",  # Wildcard: all permissions
        ],
    },
    {
        "name": "admin",
        "display_name": "管理员",
        "description": "系统管理员，可管理用户和角色，访问所有数据集",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": False,
        "sort_order": 1,
        "permissions": [
            # User management
            Permissions.USER_MANAGE,
            # Role management
            Permissions.ROLE_READ,
            Permissions.ROLE_CREATE,
            Permissions.ROLE_UPDATE,
            Permissions.ROLE_DELETE,
            # Dataset - full access
            Permissions.DATASET_READ_ALL,
            Permissions.DATASET_UPDATE_ALL,
            Permissions.DATASET_DELETE_ALL,
            Permissions.DATASET_CREATE,
            # System
            Permissions.SYSTEM_MANAGE,
        ],
    },
    {
        "name": "user",
        "display_name": "普通用户",
        "description": "默认用户角色，可创建数据集，管理自己的数据集",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": True,  # Auto-assigned to new users
        "sort_order": 2,
        "permissions": [
            # Dataset - create and manage own
            Permissions.DATASET_CREATE,
            Permissions.DATASET_READ_OWNED,
            Permissions.DATASET_UPDATE_OWNED,
            Permissions.DATASET_DELETE_OWNED,
            Permissions.DATASET_ASSIGN_OWNED,
            Permissions.DATASET_EXPORT_OWNED,
            Permissions.DATASET_IMPORT_OWNED,
        ],
    },
    
    # ========================================================================
    # Resource Roles (Dataset-level Permissions)
    # ========================================================================
    {
        "name": "dataset_owner",
        "display_name": "数据集所有者",
        "description": "数据集的创建者，拥有完全控制权",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 10,
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_DELETE,
            Permissions.DATASET_ASSIGN,
            Permissions.DATASET_EXPORT,
            Permissions.DATASET_IMPORT,
            # Sample
            Permissions.SAMPLE_MANAGE,
            # Label
            Permissions.LABEL_MANAGE,
            # Annotation - full access
            Permissions.ANNOTATION_MANAGE,
        ],
    },
    {
        "name": "dataset_manager",
        "display_name": "数据集管理员",
        "description": "可管理数据集的大部分功能，但不能删除数据集",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 11,
        "parent": "dataset_annotator",  # Will be linked after creation
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_ASSIGN,
            Permissions.DATASET_EXPORT,
            Permissions.DATASET_IMPORT,
            # Sample
            Permissions.SAMPLE_MANAGE,
            # Label
            Permissions.LABEL_MANAGE,
            # Annotation - full access including review
            Permissions.ANNOTATION_MANAGE,
            Permissions.ANNOTATION_REVIEW,
        ],
    },
    {
        "name": "dataset_senior_annotator",
        "display_name": "高级标注员",
        "description": "可查看所有标注，但只能修改和删除自己的标注",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 12,
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            # Sample
            Permissions.SAMPLE_READ,
            # Label
            Permissions.LABEL_READ,
            # Annotation - read all, modify self
            Permissions.ANNOTATION_READ,        # Can see all annotations
            Permissions.ANNOTATION_CREATE,      # Can create
            Permissions.ANNOTATION_UPDATE_SELF, # Can only update own
            Permissions.ANNOTATION_DELETE_SELF, # Can only delete own
        ],
    },
    {
        "name": "dataset_annotator",
        "display_name": "标注员",
        "description": "只能查看和操作自己的标注",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 13,
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            # Sample
            Permissions.SAMPLE_READ,
            # Label
            Permissions.LABEL_READ,
            # Annotation - self only
            Permissions.ANNOTATION_READ_SELF,   # Can only see own annotations
            Permissions.ANNOTATION_CREATE,      # Can create
            Permissions.ANNOTATION_UPDATE_SELF, # Can only update own
            Permissions.ANNOTATION_DELETE_SELF, # Can only delete own
        ],
    },
    {
        "name": "dataset_reviewer",
        "display_name": "审核员",
        "description": "可查看所有标注并进行审核，不能修改标注",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 14,
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            # Sample
            Permissions.SAMPLE_READ,
            # Label
            Permissions.LABEL_READ,
            # Annotation - read and review
            Permissions.ANNOTATION_READ,
            Permissions.ANNOTATION_REVIEW,
        ],
    },
    {
        "name": "dataset_viewer",
        "display_name": "查看者",
        "description": "只能查看数据集内容，无法进行任何修改",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 15,
        "permissions": [
            # Dataset
            Permissions.DATASET_READ,
            # Sample
            Permissions.SAMPLE_READ,
            # Label
            Permissions.LABEL_READ,
            # Annotation - read only
            Permissions.ANNOTATION_READ,
        ],
    },
]


def init_preset_roles(session: Session) -> Dict[str, Role]:
    """
    Initialize preset roles in the database.
    
    Should be called during system initialization.
    Only creates roles that don't already exist.
    
    Returns:
        Dictionary mapping role names to Role objects
    """
    roles: Dict[str, Role] = {}
    parent_mappings: Dict[str, str] = {}  # role_name -> parent_name
    
    for preset in PRESET_ROLES:
        # Check if role already exists
        existing = session.exec(
            select(Role).where(Role.name == preset["name"])
        ).first()
        
        if existing:
            roles[preset["name"]] = existing
            continue
        
        # Create role
        role = Role(
            name=preset["name"],
            display_name=preset["display_name"],
            description=preset.get("description"),
            type=preset["type"],
            is_system=preset.get("is_system", True),
            is_default=preset.get("is_default", False),
            sort_order=preset.get("sort_order", 0),
        )
        session.add(role)
        session.flush()  # Get ID
        
        # Store parent mapping for later
        if "parent" in preset:
            parent_mappings[preset["name"]] = preset["parent"]
        
        # Create permissions
        for perm in preset.get("permissions", []):
            rp = RolePermission(
                role_id=role.id,
                permission=perm,
            )
            session.add(rp)
        
        roles[preset["name"]] = role
    
    # Set up parent relationships
    for role_name, parent_name in parent_mappings.items():
        if role_name in roles and parent_name in roles:
            roles[role_name].parent_id = roles[parent_name].id
            session.add(roles[role_name])
    
    session.commit()
    
    return roles


def get_default_role(session: Session) -> Role:
    """Get the default role for new users."""
    return session.exec(
        select(Role).where(Role.is_default == True, Role.type == RoleType.SYSTEM)
    ).first()


def get_role_by_name(session: Session, name: str) -> Role:
    """Get a role by its name."""
    return session.exec(
        select(Role).where(Role.name == name)
    ).first()


def get_dataset_owner_role(session: Session) -> Role:
    """Get the dataset_owner role."""
    return get_role_by_name(session, "dataset_owner")
