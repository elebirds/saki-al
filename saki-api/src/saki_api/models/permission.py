"""
Permission system models for RBAC (Role-Based Access Control).

Includes:
- Role enums (GlobalRole, ResourceRole)
- Permission enum
- RolePermission mapping table
- DatasetMember table for resource-level permissions
"""

from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING

from saki_api.models.base import TimestampMixin, UUIDMixin
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from saki_api.models.user import User
    from saki_api.models.dataset import Dataset


# ============================================================================
# Role Enums
# ============================================================================

class GlobalRole(str, Enum):
    """全局角色：系统级角色"""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    ANNOTATOR = "annotator"
    VIEWER = "viewer"


class ResourceRole(str, Enum):
    """资源角色：数据集/项目级别的角色"""
    OWNER = "owner"
    MANAGER = "manager"
    ANNOTATOR = "annotator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


# ============================================================================
# Permission Enum
# ============================================================================

class Permission(str, Enum):
    """权限枚举：定义所有可用的权限"""
    # 用户管理
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_MANAGE_ROLES = "user:manage_roles"

    # 数据集全局权限
    DATASET_CREATE = "dataset:create"
    DATASET_READ_ALL = "dataset:read_all"
    DATASET_UPDATE_ALL = "dataset:update_all"
    DATASET_DELETE_ALL = "dataset:delete_all"

    # 数据集资源权限
    DATASET_READ = "dataset:read"
    DATASET_UPDATE = "dataset:update"
    DATASET_DELETE = "dataset:delete"
    DATASET_MANAGE_MEMBERS = "dataset:manage_members"
    DATASET_UPLOAD = "dataset:upload"
    DATASET_EXPORT = "dataset:export"

    # 样本权限（继承自数据集）
    SAMPLE_READ = "sample:read"
    SAMPLE_UPDATE = "sample:update"
    SAMPLE_DELETE = "sample:delete"

    # 标注权限（继承自数据集）
    ANNOTATION_READ = "annotation:read"
    ANNOTATION_MODIFY = "annotation:modify"  # 合并create/update/delete
    ANNOTATION_REVIEW = "annotation:review"

    # 系统配置
    SYSTEM_CONFIG = "system:config"


# ============================================================================
# Role-Permission Mapping
# ============================================================================

class RolePermission(SQLModel, table=True):
    """
    角色-权限关联表：定义每个角色拥有哪些权限
    
    资源类型：
    - None: 全局权限
    - "dataset": 数据集资源权限
    """
    __tablename__ = "role_permission"

    role: str = Field(primary_key=True, description="角色名称（GlobalRole或ResourceRole）")
    permission: Permission = Field(primary_key=True, description="权限")
    resource_type: Optional[str] = Field(
        default=None,
        description="资源类型：None表示全局权限，'dataset'表示数据集资源权限"
    )


# ============================================================================
# Dataset Member (Resource-level permissions)
# ============================================================================

class DatasetMember(SQLModel, table=True):
    """
    数据集成员表：用户-数据集-角色关联
    
    用于实现数据集级别的细粒度权限控制
    """
    __tablename__ = "dataset_member"

    dataset_id: str = Field(
        foreign_key="dataset.id",
        primary_key=True,
        description="数据集ID"
    )
    user_id: str = Field(
        foreign_key="user.id",
        primary_key=True,
        description="用户ID"
    )
    role: ResourceRole = Field(
        description="用户在该数据集中的角色"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="添加时间"
    )
    created_by: str = Field(
        foreign_key="user.id",
        description="谁添加的这个成员"
    )

    # Relationships
    dataset: "Dataset" = Relationship(back_populates="members")
    user: "User" = Relationship(
        back_populates="dataset_memberships",
        sa_relationship_kwargs={
            "foreign_keys": "[DatasetMember.user_id]"
        }
    )
    creator: "User" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[DatasetMember.created_by]"
        }
    )


# ============================================================================
# Schema Models
# ============================================================================

class DatasetMemberCreate(SQLModel):
    """创建数据集成员的请求模型"""
    user_id: str = Field(description="用户ID")
    role: ResourceRole = Field(description="角色")


class DatasetMemberRead(SQLModel):
    """读取数据集成员的响应模型"""
    dataset_id: str
    user_id: str
    role: ResourceRole
    created_at: datetime
    created_by: str
    # 可选：包含用户信息
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None


class DatasetMemberUpdate(SQLModel):
    """更新数据集成员的请求模型"""
    role: ResourceRole = Field(description="新角色")
