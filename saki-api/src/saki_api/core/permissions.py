"""
Permission checking logic for RBAC system.

Provides functions to check if a user has specific permissions,
considering both global roles and resource-level permissions.
"""

from typing import Optional

from saki_api.models.dataset import Dataset
from saki_api.models.permission import (
    GlobalRole, ResourceRole, Permission,
    RolePermission, DatasetMember
)
from saki_api.models.sample import Sample
from saki_api.models.user import User
from sqlmodel import Session, select

# ============================================================================
# Role-Permission Mappings (Hardcoded for now, can be moved to DB later)
# ============================================================================

# 全局角色权限映射
GLOBAL_ROLE_PERMISSIONS: dict[GlobalRole, list[Permission]] = {
    GlobalRole.SUPER_ADMIN: list(Permission),  # 所有权限
    GlobalRole.ADMIN: [
        Permission.USER_CREATE,
        Permission.USER_READ,
        Permission.USER_UPDATE,
        Permission.USER_DELETE,
        Permission.USER_MANAGE_ROLES,
        Permission.DATASET_CREATE,
        Permission.DATASET_READ_ALL,
        Permission.DATASET_UPDATE_ALL,
        Permission.DATASET_DELETE_ALL,
        Permission.SYSTEM_CONFIG,
    ],
    GlobalRole.ANNOTATOR: [
        Permission.DATASET_READ_ALL,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_MODIFY,
    ],
    GlobalRole.VIEWER: [
        Permission.DATASET_READ_ALL,
        Permission.ANNOTATION_READ,
    ],
}

# 资源角色权限映射
RESOURCE_ROLE_PERMISSIONS: dict[ResourceRole, list[Permission]] = {
    ResourceRole.OWNER: [
        # 所有者拥有所有数据集相关权限
        Permission.DATASET_READ,
        Permission.DATASET_UPDATE,
        Permission.DATASET_DELETE,
        Permission.DATASET_MANAGE_MEMBERS,
        Permission.DATASET_UPLOAD,
        Permission.DATASET_EXPORT,
        Permission.SAMPLE_READ,
        Permission.SAMPLE_UPDATE,
        Permission.SAMPLE_DELETE,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_MODIFY,
        Permission.ANNOTATION_REVIEW,
    ],
    ResourceRole.MANAGER: [
        Permission.DATASET_READ,
        Permission.DATASET_UPDATE,
        Permission.DATASET_DELETE,
        Permission.DATASET_MANAGE_MEMBERS,
        Permission.DATASET_UPLOAD,
        Permission.DATASET_EXPORT,
        Permission.SAMPLE_READ,
        Permission.SAMPLE_UPDATE,
        Permission.SAMPLE_DELETE,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_MODIFY,
        Permission.ANNOTATION_REVIEW,
    ],
    ResourceRole.ANNOTATOR: [
        Permission.DATASET_READ,
        Permission.SAMPLE_READ,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_MODIFY,
    ],
    ResourceRole.REVIEWER: [
        Permission.DATASET_READ,
        Permission.SAMPLE_READ,
        Permission.ANNOTATION_READ,
        Permission.ANNOTATION_REVIEW,
    ],
    ResourceRole.VIEWER: [
        Permission.DATASET_READ,
        Permission.SAMPLE_READ,
        Permission.ANNOTATION_READ,
    ],
}


# ============================================================================
# Permission Checking Functions
# ============================================================================

def _is_dataset_owner(user_id: str, dataset_id: str, session: Session) -> bool:
    """检查用户是否是数据集的所有者"""
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        return False
    return dataset.owner_id == user_id


def _get_dataset_member_role(
        user_id: str, dataset_id: str, session: Session
) -> Optional[ResourceRole]:
    """获取用户在数据集中的角色"""
    member = session.exec(
        select(DatasetMember).where(
            DatasetMember.user_id == user_id,
            DatasetMember.dataset_id == dataset_id
        )
    ).first()
    return member.role if member else None


def _check_global_permission(
        global_role: GlobalRole, permission: Permission
) -> bool:
    """检查全局角色是否拥有权限"""
    if global_role == GlobalRole.SUPER_ADMIN:
        return True
    permissions = GLOBAL_ROLE_PERMISSIONS.get(global_role, [])
    return permission in permissions


def _check_resource_permission(
        resource_role: ResourceRole, permission: Permission
) -> bool:
    """检查资源角色是否拥有权限"""
    permissions = RESOURCE_ROLE_PERMISSIONS.get(resource_role, [])
    return permission in permissions


def _get_dataset_id_from_sample(sample_id: str, session: Session) -> Optional[str]:
    """通过样本ID获取数据集ID"""
    sample = session.get(Sample, sample_id)
    return sample.dataset_id if sample else None


def check_permission(
        user: User,
        permission: Permission,
        resource_type: Optional[str] = None,  # "dataset" 或 "sample"
        resource_id: Optional[str] = None,
        session: Optional[Session] = None
) -> bool:
    """
    检查用户是否拥有指定权限
    
    检查顺序：
    1. 超级管理员拥有所有权限
    2. 如果是数据集资源，检查是否为所有者
    3. 检查资源级权限（DatasetMember）
    4. 检查全局权限（User.global_role）
    
    Args:
        user: 用户对象
        permission: 要检查的权限
        resource_type: 资源类型（"dataset" 或 "sample"）
        resource_id: 资源ID（数据集ID或样本ID）
        session: 数据库会话（如果提供resource_id则必需）
    
    Returns:
        bool: 是否拥有权限
    """
    if not session:
        # 如果没有提供session，只能检查全局权限
        return _check_global_permission(user.global_role, permission)

    # 1. 超级管理员拥有所有权限
    if user.global_role == GlobalRole.SUPER_ADMIN:
        return True

    # 2. 如果是资源权限，检查所有权和资源级权限
    if resource_type and resource_id:
        dataset_id = resource_id

        # 如果是sample，先获取dataset_id
        if resource_type == "sample":
            dataset_id = _get_dataset_id_from_sample(resource_id, session)
            if not dataset_id:
                return False

        # 检查是否为所有者
        if _is_dataset_owner(user.id, dataset_id, session):
            return True

        # 检查资源级权限
        resource_role = _get_dataset_member_role(user.id, dataset_id, session)
        if resource_role and _check_resource_permission(resource_role, permission):
            return True

    # 3. 检查全局权限
    return _check_global_permission(user.global_role, permission)


def require_permission(
        permission: Permission,
        resource_type: Optional[str] = None,
        resource_id_param: Optional[str] = None,
        resource_id_from_body: Optional[str] = None
):
    """
    创建权限检查依赖注入函数
    
    使用示例：
    # 从路径参数获取资源ID
    @router.get("/datasets/{dataset_id}")
    def get_dataset(
        dataset_id: str,
        current_user: User = Depends(require_permission(
            Permission.DATASET_READ, "dataset", "dataset_id"
        )),
        session: Session = Depends(get_session)
    ):
        ...
    
    # 从请求体获取资源ID
    @router.post("/annotations/save")
    def save_annotations(
        request: BatchSaveRequest,
        current_user: User = Depends(require_permission(
            Permission.ANNOTATION_MODIFY, "sample", None, "sample_id"
        )),
        session: Session = Depends(get_session)
    ):
        ...
    
    Args:
        permission: 需要的权限
        resource_type: 资源类型（"dataset" 或 "sample"）
        resource_id_param: URL路径参数名，用于从路径中获取资源ID
        resource_id_from_body: 请求体字段名，用于从请求体中获取资源ID
    
    Returns:
        依赖注入函数
    """
    from fastapi import Depends, HTTPException, Request
    from saki_api.api.deps import get_current_user, get_session

    async def permission_checker(
            request: Request,
            current_user: User = Depends(get_current_user),
            session: Session = Depends(get_session)
    ) -> User:
        resource_id = None

        # 优先从路径参数获取
        if resource_id_param:
            resource_id = request.path_params.get(resource_id_param)

        # 注意：从请求体读取会消耗请求体，导致后续处理函数无法读取
        # 对于需要从请求体获取资源ID的情况，建议在函数内部进行权限检查
        # 这里我们只处理路径参数的情况

        if not check_permission(
                current_user, permission, resource_type, resource_id, session
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission.value}"
            )
        return current_user

    return permission_checker
