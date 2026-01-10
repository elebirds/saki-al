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
        "is_super_admin": True,
        "is_admin": False,
        "sort_order": 0,
        "permissions": [
            Permissions.ALL_PERMISSIONS,  # *:*:all - 全局所有权限
            Permissions.ROLE_ASSIGN_ADMIN,  # 授权管理员权限
        ],
    },
    {
        "name": "admin",
        "display_name": "管理员",
        "description": "系统管理员，可管理用户和角色，完全访问所有数据集及其内容",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": False,
        "is_super_admin": False,
        "is_admin": True,
        "sort_order": 1,
        "permissions": [
            # User management - 用户管理
            Permissions.USER_CREATE,
            Permissions.USER_READ,
            Permissions.USER_UPDATE,
            Permissions.USER_DELETE,
            Permissions.USER_LIST,
            # Role management - 角色管理
            Permissions.ROLE_CREATE,
            Permissions.ROLE_READ,
            Permissions.ROLE_UPDATE,
            Permissions.ROLE_DELETE,
            Permissions.ROLE_ASSIGN,
            Permissions.ROLE_REVOKE,
            # Dataset - 数据集完全访问
            Permissions.DATASET_CREATE_ALL,
            Permissions.DATASET_READ_ALL,
            Permissions.DATASET_UPDATE_ALL,
            Permissions.DATASET_DELETE_ALL,
            Permissions.DATASET_ASSIGN_ALL,
            Permissions.DATASET_EXPORT_ALL,
            Permissions.DATASET_IMPORT_ALL,
            # Sample - 样本完全访问
            Permissions.SAMPLE_READ_ALL,
            Permissions.SAMPLE_CREATE_ALL,
            Permissions.SAMPLE_UPDATE_ALL,
            Permissions.SAMPLE_DELETE_ALL,
            # Label - 标签完全访问
            Permissions.LABEL_READ_ALL,
            Permissions.LABEL_CREATE_ALL,
            Permissions.LABEL_UPDATE_ALL,
            Permissions.LABEL_DELETE_ALL,
            # Annotation - 标注完全访问
            Permissions.ANNOTATION_READ_ALL,
            Permissions.ANNOTATION_MODIFY_ALL,
        ],
    },
    {
        "name": "creator",
        "display_name": "创作者",
        "description": "可创建和管理自己的数据集，可分配成员",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": False,
        "sort_order": 2,
        "permissions": [
            # Dataset - 创建和管理自己的数据集
            Permissions.DATASET_CREATE_ALL,
            # User list - 用于成员选择
            Permissions.USER_LIST,
        ],
    },
    {
        "name": "user",
        "display_name": "普通用户",
        "description": "默认用户角色，只能访问被分配的数据集",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": True,  # 新用户自动分配此角色
        "sort_order": 3,
        "permissions": [
            # 无任何系统级权限 - 只能访问被分配的数据集资源
        ],
    },

    # ========================================================================
    # Resource Roles (Dataset-level Permissions)
    # 资源级角色 - 这些角色的权限在特定数据集范围内生效
    # ========================================================================
    {
        "name": "dataset_owner",
        "display_name": "数据集所有者",
        "description": "数据集的创建者，拥有完全控制权",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 10,
        "permissions": [
            # Dataset - 数据集完全控制
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_DELETE,
            Permissions.DATASET_ASSIGN,
            Permissions.DATASET_EXPORT,
            Permissions.DATASET_IMPORT,
            # Sample - 样本完全控制
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
            Permissions.SAMPLE_DELETE,
            # Label - 标签完全控制
            Permissions.LABEL_READ,
            Permissions.LABEL_CREATE,
            Permissions.LABEL_UPDATE,
            Permissions.LABEL_DELETE,
            # Annotation - 标注完全控制
            Permissions.ANNOTATION_READ,
            Permissions.ANNOTATION_MODIFY,
            # User list - 用于成员选择
            Permissions.USER_LIST,
        ],
    },
    {
        "name": "dataset_manager",
        "display_name": "数据集管理员",
        "description": "可管理数据集的大部分功能，但不能删除数据集",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 11,
        "permissions": [
            # Dataset - 除删除外的管理权限
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_ASSIGN,
            Permissions.DATASET_EXPORT,
            Permissions.DATASET_IMPORT,
            # Sample - 样本完全控制
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
            Permissions.SAMPLE_DELETE,
            # Label - 标签完全控制
            Permissions.LABEL_READ,
            Permissions.LABEL_CREATE,
            Permissions.LABEL_UPDATE,
            Permissions.LABEL_DELETE,
            # Annotation - 标注完全控制
            Permissions.ANNOTATION_READ,
            Permissions.ANNOTATION_MODIFY,
            # User list - 用于成员选择
            Permissions.USER_LIST,
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
            # Dataset - 只读
            Permissions.DATASET_READ,
            # Sample - 只读
            Permissions.SAMPLE_READ,
            # Label - 只读
            Permissions.LABEL_READ,
            # Annotation - 读取全部，修改自己的
            Permissions.ANNOTATION_READ,  # 可以看到所有标注
            Permissions.ANNOTATION_MODIFY_SELF,  # 只能修改自己的标注
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
            # Dataset - 只读
            Permissions.DATASET_READ,
            # Sample - 只读
            Permissions.SAMPLE_READ,
            # Label - 只读
            Permissions.LABEL_READ,
            # Annotation - 只能操作自己的
            Permissions.ANNOTATION_READ_SELF,  # 只能看自己的标注
            Permissions.ANNOTATION_MODIFY_SELF,  # 只能修改自己的标注
        ],
    },
    {
        "name": "dataset_viewer",
        "display_name": "查看者",
        "description": "只能查看数据集内容，无法进行任何修改",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 14,
        "permissions": [
            # Dataset - 只读
            Permissions.DATASET_READ,
            # Sample - 只读
            Permissions.SAMPLE_READ,
            # Label - 只读
            Permissions.LABEL_READ,
            # Annotation - 只读
            Permissions.ANNOTATION_READ,
        ],
    },
]


def init_preset_roles(session: Session, update_existing: bool = True) -> Dict[str, Role]:
    """
    Initialize preset roles in the database.
    
    Should be called during system initialization.
    
    Args:
        session: Database session
        update_existing: If True, update permissions for existing system roles
    
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

            # Update permissions and flags for existing system roles if requested
            if update_existing and existing.is_system:
                # Update is_super_admin and is_admin flags
                existing.is_super_admin = preset.get("is_super_admin", False)
                existing.is_admin = preset.get("is_admin", False)
                session.add(existing)

                # Get current permissions
                current_perms = session.exec(
                    select(RolePermission).where(RolePermission.role_id == existing.id)
                ).all()
                current_perm_set = {rp.permission for rp in current_perms}
                preset_perm_set = set(preset.get("permissions", []))

                # Add missing permissions
                for perm in preset_perm_set - current_perm_set:
                    rp = RolePermission(
                        role_id=existing.id,
                        permission=perm,
                    )
                    session.add(rp)

                # Optionally remove extra permissions not in preset
                # (commented out to allow custom additions to system roles)
                # for perm in current_perm_set - preset_perm_set:
                #     for rp in current_perms:
                #         if rp.permission == perm:
                #             session.delete(rp)

            continue

        # Create role
        role = Role(
            name=preset["name"],
            display_name=preset["display_name"],
            description=preset.get("description"),
            type=preset["type"],
            is_system=preset.get("is_system", True),
            is_default=preset.get("is_default", False),
            is_super_admin=preset.get("is_super_admin", False),
            is_admin=preset.get("is_admin", False),
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
