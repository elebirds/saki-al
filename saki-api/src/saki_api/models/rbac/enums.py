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
    - ASSIGNED: Access to all items within assigned resources (member level)
    - SELF: Access only to items created by the user within assigned resources
    """
    ALL = "all"
    ASSIGNED = "assigned"
    SELF = "self"


VALID_SCOPE_STRS = [s.value for s in Scope]


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
# Predefined Permission Constants (for convenience)
# ============================================================================
# 注意：以下权限是按照权限范围从小到大排序的，即：ALL > ASSIGNED > SELF
# ALL：全局允许，系统级权限，通常用于管理员角色
# ASSIGNED：成员允许，通常用于数据集、项目等资源的成员
# SELF：自己允许，通常用于标注者自己标注的标注
# ============================================================================
# ALL属于系统级角色的权限
# ASSIGNED属于资源级角色的权限

class Permissions:
    """
    Predefined permission constants for common use cases.
    
    All permission constants are strings in format "target:action:scope".
    You can convert them to Permission objects using Permission.from_string() or parse_permission().
    
    Examples:
        >>> from saki_api.models.rbac import Permission, parse_permission
        >>> perm = parse_permission(Permissions.DATASET_READ)
        >>> print(perm.target)  # "dataset"
        >>> print(perm.action)  # "read"
        >>> print(perm.scope)   # "assigned"
    """
    ALL_PERMISSIONS = "*:*:all"  # 全局允许：所有权限

    @staticmethod
    def to_permission(permission_str: str) -> "Permission":
        """
        Convert a permission string to a Permission object.
        
        This is a convenience method that imports Permission class dynamically
        to avoid circular imports.
        
        Args:
            permission_str: Permission string (e.g., "dataset:read:all")
            
        Returns:
            Permission object
            
        Examples:
            >>> perm = Permissions.to_permission(Permissions.DATASET_READ)
            >>> print(perm.target)  # "dataset"
        """
        from saki_api.models.rbac.permission import Permission
        return Permission.from_string(permission_str)

    # ============================================================================
    # User Management Permissions
    # ============================================================================
    USER_CREATE = "user:create:all"  # 全局允许：新建用户
    USER_READ = "user:read:all"  # 全局允许：读取用户信息，包括其拥有的角色
    USER_UPDATE = "user:update:all"  # 全局允许：修改用户信息（不包括角色信息）
    USER_DELETE = "user:delete:all"  # 全局允许：删除用户
    USER_LIST = "user:list:all"  # 全局允许：读取用户列表（用于用户选择）
    USER_ROLE_READ = "user:role_read:all"  # 全局允许：查看用户角色信息

    # ============================================================================
    # Role Management Permissions
    # ============================================================================
    ROLE_CREATE = "role:create:all"  # 全局允许：新建角色
    ROLE_READ = "role:read:all"  # 全局允许：读取角色信息
    ROLE_UPDATE = "role:update:all"  # 全局允许：修改角色信息
    ROLE_DELETE = "role:delete:all"  # 全局允许：删除角色
    ROLE_ASSIGN = "role:assign:all"  # 全局允许：分配角色给用户（除授权管理员权限）
    ROLE_REVOKE = "role:revoke:all"  # 全局允许：撤销角色给用户
    ROLE_ASSIGN_ADMIN = "role:assign_admin:all"  # 全局允许：授权管理员权限（只有超级管理员拥有）

    # ============================================================================
    # Dataset Permissions
    # ============================================================================
    # Dataset - global scope
    DATASET_CREATE_ALL = "dataset:create:all"  # 全局允许：新建数据集
    DATASET_READ_ALL = "dataset:read:all"  # 全局允许：读取数据集信息
    DATASET_UPDATE_ALL = "dataset:update:all"  # 全局允许：修改数据集信息
    DATASET_DELETE_ALL = "dataset:delete:all"  # 全局允许：删除数据集
    DATASET_ASSIGN_ALL = "dataset:assign:all"  # 全局允许：管理数据集成员和权限
    # Dataset - assigned scope
    DATASET_READ = "dataset:read:assigned"  # 成员允许：读取数据集信息
    DATASET_UPDATE = "dataset:update:assigned"  # 成员允许：修改数据集信息
    DATASET_DELETE = "dataset:delete:assigned"  # 成员允许：删除数据集（应该永远不分配此权限）
    DATASET_ASSIGN = "dataset:assign:assigned"  # 成员允许：管理数据集成员和权限

    # ============================================================================
    # Sample Permissions
    # ============================================================================
    # Sample - global scope
    SAMPLE_READ_ALL = "sample:read:all"  # 全局允许：读取样本信息
    SAMPLE_CREATE_ALL = "sample:create:all"  # 全局允许：新建样本（即，上传样本）
    SAMPLE_UPDATE_ALL = "sample:update:all"  # 全局允许：更新样本（即，更新样本信息）
    SAMPLE_DELETE_ALL = "sample:delete:all"  # 全局允许：删除样本（即，删除样本）
    # Sample - assigned scope
    SAMPLE_READ = "sample:read:assigned"  # 成员允许：读取样本信息
    SAMPLE_CREATE = "sample:create:assigned"  # 成员允许：新建样本（即，上传样本）
    SAMPLE_UPDATE = "sample:update:assigned"  # 成员允许：更新样本（即，更新样本信息）
    SAMPLE_DELETE = "sample:delete:assigned"  # 成员允许：删除样本（即，删除样本）

    # ============================================================================
    # Project Permissions (L2 Layer)
    # ============================================================================
    # Project - global scope
    PROJECT_CREATE_ALL = "project:create:all"  # 全局允许：新建项目
    PROJECT_READ_ALL = "project:read:all"  # 全局允许：读取项目信息
    PROJECT_UPDATE_ALL = "project:update:all"  # 全局允许：修改项目信息
    PROJECT_DELETE_ALL = "project:delete:all"  # 全局允许：删除项目
    PROJECT_ASSIGN_ALL = "project:assign:all"  # 全局允许：管理项目成员和权限
    # Project - assigned scope
    PROJECT_READ = "project:read:assigned"  # 成员允许：读取项目信息
    PROJECT_UPDATE = "project:update:assigned"  # 成员允许：修改项目信息
    PROJECT_DELETE = "project:delete:assigned"  # 成员允许：删除项目（应该永远不分配此权限）
    PROJECT_ASSIGN = "project:assign:assigned"  # 成员允许：管理项目成员和权限

    # ============================================================================
    # Label Permissions (L2 Layer)
    # ============================================================================
    LABEL_MANAGE = "label:manage:assigned"  # 成员允许：创建/更新/删除项目标签
    LABEL_READ = "label:read:assigned"  # 成员允许：读取项目标签

    # ============================================================================
    # Annotation Permissions (L2 Layer)
    # ============================================================================
    ANNOTATE = "annotation:create:assigned"  # 成员允许：创建/修改标注
    ANNOTATION_READ = "annotation:read:assigned"  # 成员允许：读取标注
    ANNOTATION_DELETE = "annotation:delete:assigned"  # 成员允许：删除标注
    # Annotation - self scope (reserved)
    ANNOTATE_SELF = "annotation:create:self"  # 仅本人：创建/修改标注（预留）
    ANNOTATION_READ_SELF = "annotation:read:self"  # 仅本人：读取标注（预留）
    ANNOTATION_DELETE_SELF = "annotation:delete:self"  # 仅本人：删除标注（预留）

    # ============================================================================
    # Commit Permissions (L2 Layer)
    # ============================================================================
    COMMIT_CREATE = "commit:create:assigned"  # 成员允许：创建 commit（保存标注）
    COMMIT_READ = "commit:read:assigned"  # 成员允许：读取 commit 历史
    # Commit - self scope (reserved)
    COMMIT_CREATE_SELF = "commit:create:self"  # 仅本人：创建 commit（预留）
    COMMIT_READ_SELF = "commit:read:self"  # 仅本人：读取 commit（预留）

    # ============================================================================
    # Branch Permissions (L2 Layer)
    # ============================================================================
    BRANCH_MANAGE = "branch:manage:assigned"  # 成员允许：创建/删除分支
    BRANCH_READ = "branch:read:assigned"  # 成员允许：读取分支信息
    BRANCH_SWITCH = "branch:switch:assigned"  # 成员允许：切换分支（移动 HEAD 指针）
    # Branch - self scope (reserved)
    BRANCH_READ_SELF = "branch:read:self"  # 仅本人：读取分支信息（预留）

    # ============================================================================
    # Active Learning / Runtime Permissions (L3 Layer)
    # ============================================================================
    LOOP_READ = "loop:read:assigned"  # 成员允许：读取 Loop 信息
    LOOP_MANAGE = "loop:manage:assigned"  # 成员允许：创建/启动/暂停/停止 Loop
    JOB_READ = "job:read:assigned"  # 成员允许：读取任务信息/事件/指标
    JOB_MANAGE = "job:manage:assigned"  # 成员允许：创建/停止任务
    MODEL_READ = "model:read:assigned"  # 成员允许：读取模型信息
    MODEL_MANAGE = "model:manage:assigned"  # 成员允许：注册/晋升模型
