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
    """
    ALL_PERMISSIONS = "*:*:all"  # 全局允许：所有权限

    # ============================================================================
    # User Management Permissions
    # ============================================================================
    USER_CREATE = "user:create:all"  # 全局允许：新建用户
    USER_READ = "user:read:all"  # 全局允许：读取用户信息，包括其拥有的角色
    USER_UPDATE = "user:update:all"  # 全局允许：修改用户信息（不包括角色信息）
    USER_DELETE = "user:delete:all"  # 全局允许：删除用户
    USER_LIST = "user:list:all"  # 全局允许：读取用户列表（用于用户选择）

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
    DATASET_ASSIGN_ALL = "dataset:assign:all"  # 全局允许：分配数据集权限给用户
    DATASET_EXPORT_ALL = "dataset:export:all"  # 全局允许：导出数据集
    DATASET_IMPORT_ALL = "dataset:import:all"  # 全局允许：导入数据集
    # Dataset - assigned scope
    DATASET_READ = "dataset:read:assigned"  # 成员允许：读取数据集信息
    DATASET_UPDATE = "dataset:update:assigned"  # 成员允许：修改数据集信息
    DATASET_DELETE = "dataset:delete:assigned"  # 成员允许：删除数据集（应该永远不分配此权限）
    DATASET_ASSIGN = "dataset:assign:assigned"  # 成员允许：分配数据集权限给用户
    DATASET_EXPORT = "dataset:export:assigned"  # 成员允许：导出数据集
    DATASET_IMPORT = "dataset:import:assigned"  # 成员允许：导入数据集

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
    # Label Permissions
    # ============================================================================
    # Label - global scope
    LABEL_READ_ALL = "label:read:all"  # 全局允许：读取标签信息
    LABEL_CREATE_ALL = "label:create:all"  # 全局允许：新建标签
    LABEL_UPDATE_ALL = "label:update:all"  # 全局允许：更新标签
    LABEL_DELETE_ALL = "label:delete:all"  # 全局允许：删除标签
    # Label - assigned scope
    LABEL_READ = "label:read:assigned"  # 成员允许：读取标签信息
    LABEL_CREATE = "label:create:assigned"  # 成员允许：新建标签
    LABEL_UPDATE = "label:update:assigned"  # 成员允许：更新标签
    LABEL_DELETE = "label:delete:assigned"  # 成员允许：删除标签

    # ============================================================================
    # Annotation Permissions
    # ============================================================================
    # Annotation - global scope
    ANNOTATION_READ_ALL = "annotation:read:all"  # 全局允许：读取标注信息
    ANNOTATION_MODIFY_ALL = "annotation:modify:all"  # 全局允许：修改标注信息
    # Annotation - assigned scope
    ANNOTATION_READ = "annotation:read:assigned"  # 成员允许：读取标注信息
    ANNOTATION_MODIFY = "annotation:modify:assigned"  # 成员允许：修改标注信息
    # Annotation - self scope
    ANNOTATION_READ_SELF = "annotation:read:self"  # 自己允许：读取标注信息
    ANNOTATION_MODIFY_SELF = "annotation:modify:self"  # 自己允许：修改标注信息
