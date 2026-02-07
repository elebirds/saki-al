"""
Preset Role Configurations

Defines system preset roles that are created on system initialization.
These roles cannot be deleted.
"""
import logging
import uuid
from typing import List, Dict, Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.rbac import (
    Role, RoleType, RolePermission,
    Permissions,
)


# ============================================================================
# Preset Role Constants
# ============================================================================
# These UUIDs are fixed and predictable so they can be referenced directly
# without querying the database. They are deterministic based on role names.

def _generate_preset_role_id(name: str) -> uuid.UUID:
    """Generate a deterministic UUID for a preset role based on its name."""
    # Using UUID v5 with a fixed namespace for consistency
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"preset-role.{name}")


# Resource-level role IDs (used for dataset member assignments)
DATASET_OWNER_ROLE_ID = _generate_preset_role_id("dataset_owner")
DATASET_MANAGER_ROLE_ID = _generate_preset_role_id("dataset_manager")
DATASET_VIEWER_ROLE_ID = _generate_preset_role_id("dataset_viewer")
PROJECT_OWNER_ROLE_ID = _generate_preset_role_id("project_owner")
PROJECT_MANAGER_ROLE_ID = _generate_preset_role_id("project_manager")
PROJECT_VIEWER_ROLE_ID = _generate_preset_role_id("project_viewer")

# System-level role IDs
SUPER_ADMIN_ROLE_ID = _generate_preset_role_id("super_admin")
ADMIN_ROLE_ID = _generate_preset_role_id("admin")
CREATOR_ROLE_ID = _generate_preset_role_id("creator")
USER_ROLE_ID = _generate_preset_role_id("user")

# ============================================================================
# Preset Role Definitions
# ============================================================================

PRESET_ROLES: List[Dict[str, Any]] = [
    # ========================================================================
    # System Roles (Global Permissions)
    # ========================================================================
    {
        "id": SUPER_ADMIN_ROLE_ID,
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
        "is_supremo": True,
        "color": "red"
    },
    {
        "id": ADMIN_ROLE_ID,
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
            Permissions.USER_ROLE_READ,
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
            # Project - 项目完全访问
            Permissions.PROJECT_CREATE_ALL,
            Permissions.PROJECT_READ_ALL,
            Permissions.PROJECT_UPDATE_ALL,
            Permissions.PROJECT_DELETE_ALL,
            Permissions.PROJECT_ASSIGN_ALL,
            # Sample - 样本完全访问
            Permissions.SAMPLE_READ_ALL,
            Permissions.SAMPLE_CREATE_ALL,
            Permissions.SAMPLE_UPDATE_ALL,
            Permissions.SAMPLE_DELETE_ALL,
        ],
        "is_supremo": False,
        "color": "green"
    },
    {
        "id": CREATOR_ROLE_ID,
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
        "is_supremo": False,
        "color": "cyan"
    },
    {
        "id": USER_ROLE_ID,
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
        "is_supremo": False,
        "color": "yellow"
    },

    # ========================================================================
    # Resource Roles (Dataset-level Permissions)
    # 资源级角色 - 这些角色的权限在特定数据集范围内生效
    # ========================================================================
    {
        "id": DATASET_OWNER_ROLE_ID,
        "name": "dataset_owner",
        "display_name": "数据集所有者",
        "description": "数据集的创建者，拥有完全控制权和成员管理权限",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 10,
        "permissions": [
            # Dataset - 数据集完全控制
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_DELETE,
            Permissions.DATASET_ASSIGN,
            # Sample - 样本完全控制
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
            Permissions.SAMPLE_DELETE,
            # User list - 用于成员选择
            Permissions.USER_LIST,
        ],
        "is_supremo": True,
        "color": "red"
    },
    {
        "id": DATASET_MANAGER_ROLE_ID,
        "name": "dataset_manager",
        "display_name": "数据集管理员",
        "description": "可管理数据集的大部分功能（除删除外），可管理成员",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 11,
        "permissions": [
            # Dataset - 除删除外的管理权限
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.DATASET_ASSIGN,
            # Sample - 样本完全控制
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
            Permissions.SAMPLE_DELETE,
            # User list - 用于成员选择
            Permissions.USER_LIST,
        ],
        "is_supremo": False,
        "color": "green"
    },
    {
        "id": DATASET_VIEWER_ROLE_ID,
        "name": "dataset_viewer",
        "display_name": "数据集查看者",
        "description": "只能查看数据集和样本内容，无法进行任何修改",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 12,
        "permissions": [
            # Dataset - 只读
            Permissions.DATASET_READ,
            # Sample - 只读
            Permissions.SAMPLE_READ,
        ],
        "is_supremo": False,
        "color": "purple"
    },
    {
        "id": PROJECT_OWNER_ROLE_ID,
        "name": "project_owner",
        "display_name": "项目所有者",
        "description": "项目创建者，具备项目与主动学习闭环完整权限",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 20,
        "permissions": [
            Permissions.PROJECT_READ,
            Permissions.PROJECT_UPDATE,
            Permissions.PROJECT_DELETE,
            Permissions.PROJECT_ASSIGN,
            Permissions.LABEL_MANAGE,
            Permissions.LABEL_READ,
            Permissions.ANNOTATE,
            Permissions.ANNOTATION_READ,
            Permissions.ANNOTATION_DELETE,
            Permissions.COMMIT_CREATE,
            Permissions.COMMIT_READ,
            Permissions.BRANCH_MANAGE,
            Permissions.BRANCH_READ,
            Permissions.BRANCH_SWITCH,
            Permissions.LOOP_READ,
            Permissions.LOOP_MANAGE,
            Permissions.JOB_READ,
            Permissions.JOB_MANAGE,
            Permissions.MODEL_READ,
            Permissions.MODEL_MANAGE,
        ],
        "is_supremo": True,
        "color": "red",
    },
    {
        "id": PROJECT_MANAGER_ROLE_ID,
        "name": "project_manager",
        "display_name": "项目管理员",
        "description": "可管理项目与主动学习任务（不含删除项目）",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 21,
        "permissions": [
            Permissions.PROJECT_READ,
            Permissions.PROJECT_UPDATE,
            Permissions.PROJECT_ASSIGN,
            Permissions.LABEL_MANAGE,
            Permissions.LABEL_READ,
            Permissions.ANNOTATE,
            Permissions.ANNOTATION_READ,
            Permissions.COMMIT_CREATE,
            Permissions.COMMIT_READ,
            Permissions.BRANCH_MANAGE,
            Permissions.BRANCH_READ,
            Permissions.BRANCH_SWITCH,
            Permissions.LOOP_READ,
            Permissions.LOOP_MANAGE,
            Permissions.JOB_READ,
            Permissions.JOB_MANAGE,
            Permissions.MODEL_READ,
            Permissions.MODEL_MANAGE,
        ],
        "is_supremo": False,
        "color": "green",
    },
    {
        "id": PROJECT_VIEWER_ROLE_ID,
        "name": "project_viewer",
        "display_name": "项目查看者",
        "description": "仅查看项目、任务和模型信息",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 22,
        "permissions": [
            Permissions.PROJECT_READ,
            Permissions.LABEL_READ,
            Permissions.ANNOTATION_READ,
            Permissions.COMMIT_READ,
            Permissions.BRANCH_READ,
            Permissions.LOOP_READ,
            Permissions.JOB_READ,
            Permissions.MODEL_READ,
        ],
        "is_supremo": False,
        "color": "purple",
    },
]

logger = logging.getLogger(__name__)


async def init_preset_roles(session: AsyncSession) -> None:
    """
    Initialize preset roles in the database.
    
    Should be called during system initialization.
    
    Args:
        session: Database session
    
    Returns:
        Dictionary mapping role names to Role objects
    """
    for preset in PRESET_ROLES:
        # Check if role already exists
        result = await session.exec(
            select(Role).where(Role.name == preset["name"])
        )
        existing = result.first()

        if existing:
            continue
        # Create role
        role = Role(
            id=preset["id"],
            name=preset["name"],
            display_name=preset["display_name"],
            description=preset.get("description"),
            type=preset["type"],
            is_system=preset.get("is_system", True),
            is_default=preset.get("is_default", False),
            is_super_admin=preset.get("is_super_admin", False),
            is_admin=preset.get("is_admin", False),
            is_supremo=preset.get("is_supremo", False),
            sort_order=preset.get("sort_order", 0),
            color=preset.get("color", None),
        )
        session.add(role)

        # Create permissions
        for perm in preset.get("permissions", []):
            rp = RolePermission(
                role_id=role.id,
                permission=perm,
            )
            session.add(rp)

        logger.info(f"Created {preset['name']} role {preset['display_name']}")
