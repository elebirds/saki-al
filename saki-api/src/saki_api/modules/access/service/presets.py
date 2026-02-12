"""
Preset Role Configurations

Defines system preset roles that are created on system initialization.
These roles cannot be deleted.
"""
import uuid
from typing import List, Dict, Any

from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.access.domain.rbac import (
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
DATASET_EDITOR_ROLE_ID = _generate_preset_role_id("dataset_editor")
DATASET_UPLOADER_ROLE_ID = _generate_preset_role_id("dataset_uploader")
PROJECT_OWNER_ROLE_ID = _generate_preset_role_id("project_owner")
PROJECT_MANAGER_ROLE_ID = _generate_preset_role_id("project_manager")
PROJECT_VIEWER_ROLE_ID = _generate_preset_role_id("project_viewer")
PROJECT_ANNOTATOR_ROLE_ID = _generate_preset_role_id("project_annotator")
PROJECT_RUNTIME_OPERATOR_ROLE_ID = _generate_preset_role_id("project_runtime_operator")

# System-level role IDs
SUPER_ADMIN_ROLE_ID = _generate_preset_role_id("super_admin")
ADMIN_ROLE_ID = _generate_preset_role_id("admin")
CREATOR_ROLE_ID = _generate_preset_role_id("creator")
USER_ROLE_ID = _generate_preset_role_id("user")

DATASET_ROLE_NAME_PREFIX = "dataset_"
PROJECT_ROLE_NAME_PREFIX = "project_"

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
            Permissions.SYSTEM_SETTING_READ,
            Permissions.SYSTEM_SETTING_UPDATE,
            # Dataset - 数据集完全访问
            Permissions.DATASET_CREATE_ALL,
            Permissions.DATASET_READ_ALL,
            Permissions.DATASET_UPDATE_ALL,
            Permissions.DATASET_DELETE_ALL,
            Permissions.DATASET_ASSIGN_ALL,
            Permissions.DATASET_LINK_PROJECT_ALL,
            # Project - 项目完全访问
            Permissions.PROJECT_CREATE_ALL,
            Permissions.PROJECT_READ_ALL,
            Permissions.PROJECT_UPDATE_ALL,
            Permissions.PROJECT_ARCHIVE_ALL,
            Permissions.PROJECT_DELETE_ALL,
            Permissions.PROJECT_ASSIGN_ALL,
            # Sample - 样本完全访问
            Permissions.SAMPLE_READ_ALL,
            Permissions.SAMPLE_CREATE_ALL,
            Permissions.SAMPLE_UPDATE_ALL,
            Permissions.SAMPLE_DELETE_ALL,
            # Label / Annotation / Branch / Commit / Runtime - 项目全局访问
            Permissions.LABEL_MANAGE_ALL,
            Permissions.LABEL_READ_ALL,
            Permissions.ANNOTATE_ALL,
            Permissions.ANNOTATION_READ_ALL,
            Permissions.ANNOTATION_DELETE_ALL,
            Permissions.COMMIT_CREATE_ALL,
            Permissions.COMMIT_READ_ALL,
            Permissions.BRANCH_MANAGE_ALL,
            Permissions.BRANCH_READ_ALL,
            Permissions.BRANCH_SWITCH_ALL,
            Permissions.LOOP_READ_ALL,
            Permissions.LOOP_MANAGE_ALL,
            Permissions.JOB_READ_ALL,
            Permissions.JOB_MANAGE_ALL,
            Permissions.MODEL_READ_ALL,
            Permissions.MODEL_MANAGE_ALL,
        ],
        "is_supremo": False,
        "color": "green"
    },
    {
        "id": CREATOR_ROLE_ID,
        "name": "creator",
        "display_name": "创作者",
        "description": "可创建和管理自己的数据集与项目，可分配成员",
        "type": RoleType.SYSTEM,
        "is_system": True,
        "is_default": False,
        "sort_order": 2,
        "permissions": [
            # Dataset - 创建和管理自己的数据集
            Permissions.DATASET_CREATE_ALL,
            # Project - 创建和管理自己的项目
            Permissions.PROJECT_CREATE_ALL,
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
            Permissions.DATASET_LINK_PROJECT,
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
            Permissions.DATASET_LINK_PROJECT,
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
        "sort_order": 14,
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
        "id": DATASET_EDITOR_ROLE_ID,
        "name": "dataset_editor",
        "display_name": "数据集编辑者",
        "description": "可编辑数据集基础信息并管理样本，不可管理成员和删除数据集",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 12,
        "permissions": [
            Permissions.DATASET_READ,
            Permissions.DATASET_UPDATE,
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
            Permissions.SAMPLE_DELETE,
        ],
        "is_supremo": False,
        "color": "blue",
    },
    {
        "id": DATASET_UPLOADER_ROLE_ID,
        "name": "dataset_uploader",
        "display_name": "数据集上传者",
        "description": "可上传和查看样本，不可删除样本或修改数据集配置",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 13,
        "permissions": [
            Permissions.DATASET_READ,
            Permissions.SAMPLE_READ,
            Permissions.SAMPLE_CREATE,
            Permissions.SAMPLE_UPDATE,
        ],
        "is_supremo": False,
        "color": "cyan",
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
            Permissions.PROJECT_ARCHIVE,
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
            Permissions.PROJECT_ARCHIVE,
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
        "sort_order": 24,
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
    {
        "id": PROJECT_ANNOTATOR_ROLE_ID,
        "name": "project_annotator",
        "display_name": "项目标注者",
        "description": "聚焦标注与提交流程，不包含项目配置和成员管理",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 22,
        "permissions": [
            Permissions.PROJECT_READ,
            Permissions.LABEL_READ,
            Permissions.ANNOTATE,
            Permissions.ANNOTATION_READ,
            Permissions.COMMIT_CREATE,
            Permissions.COMMIT_READ,
            Permissions.BRANCH_READ,
        ],
        "is_supremo": False,
        "color": "gold",
    },
    {
        "id": PROJECT_RUNTIME_OPERATOR_ROLE_ID,
        "name": "project_runtime_operator",
        "display_name": "项目运行时操作员",
        "description": "聚焦训练/推理任务与模型生命周期，不包含项目结构配置",
        "type": RoleType.RESOURCE,
        "is_system": True,
        "sort_order": 23,
        "permissions": [
            Permissions.PROJECT_READ,
            Permissions.BRANCH_READ,
            Permissions.COMMIT_READ,
            Permissions.LOOP_READ,
            Permissions.LOOP_MANAGE,
            Permissions.JOB_READ,
            Permissions.JOB_MANAGE,
            Permissions.MODEL_READ,
            Permissions.MODEL_MANAGE,
        ],
        "is_supremo": False,
        "color": "orange",
    },
]



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
        role = result.first()

        if role is None:
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
            logger.info("已创建预置角色 role_name={} display_name={}", preset["name"], preset["display_name"])
        else:
            role.display_name = preset["display_name"]
            role.description = preset.get("description")
            role.type = preset["type"]
            role.is_system = preset.get("is_system", True)
            role.is_default = preset.get("is_default", False)
            role.is_super_admin = preset.get("is_super_admin", False)
            role.is_admin = preset.get("is_admin", False)
            role.is_supremo = preset.get("is_supremo", False)
            role.sort_order = preset.get("sort_order", 0)
            role.color = preset.get("color", None)
            session.add(role)

        await session.flush()

        # Sync permissions to match preset exactly.
        existing_perm_rows = await session.exec(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )
        existing_perms = list(existing_perm_rows.all())
        existing_perm_set = {item.permission for item in existing_perms}
        preset_perm_set = set(preset.get("permissions", []))

        for item in existing_perms:
            if item.permission not in preset_perm_set:
                await session.delete(item)

        for permission in preset_perm_set - existing_perm_set:
            session.add(
                RolePermission(
                    role_id=role.id,
                    permission=permission,
                )
            )
