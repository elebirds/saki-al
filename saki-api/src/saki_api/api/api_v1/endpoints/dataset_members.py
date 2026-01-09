"""
API endpoints for Dataset member management.

Uses the new RBAC system with ResourceMember table.
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from saki_api.api.deps import get_current_user, get_session
from saki_api.core.rbac import (
    require_permission,
    get_permission_checker,
    PermissionChecker,
    PermissionContext,
)
from saki_api.core.rbac.audit import (
    log_member_add,
    log_member_update,
    log_member_remove,
)
from saki_api.core.rbac.dependencies import get_dataset_owner
from saki_api.core.rbac.presets import get_dataset_owner_role
from saki_api.models import (
    User, Dataset,
    Role, RoleType,
    ResourceMember, ResourceMemberCreate, ResourceMemberRead, ResourceMemberUpdate,
    ResourceType,
    Permissions,
)

router = APIRouter()


@router.get("/{dataset_id}/members", response_model=List[ResourceMemberRead])
def get_dataset_members(
    dataset_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_READ,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Get all members of a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    members = session.exec(
        select(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id
        )
    ).all()
    
    result = []
    for member in members:
        user = session.get(User, member.user_id)
        role = session.get(Role, member.role_id)
        
        result.append(ResourceMemberRead(
            id=member.id,
            resource_type=member.resource_type,
            resource_id=member.resource_id,
            user_id=member.user_id,
            role_id=member.role_id,
            created_at=member.created_at,
            created_by=member.created_by,
            updated_at=member.updated_at,
            user_email=user.email if user else None,
            user_full_name=user.full_name if user else None,
            role_name=role.name if role else None,
            role_display_name=role.display_name if role else None,
        ))
    
    return result


@router.post("/{dataset_id}/members", response_model=ResourceMemberRead)
def add_dataset_member(
    dataset_id: str,
    member_in: ResourceMemberCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_ASSIGN,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Add a member to a dataset with a specific role.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    # Check if user exists
    user = session.get(User, member_in.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if role exists and is a resource role
    role = session.get(Role, member_in.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.type != RoleType.RESOURCE:
        raise HTTPException(
            status_code=400,
            detail="Must use a resource role for dataset membership"
        )
    
    # Check if already a member
    existing = session.exec(
        select(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id,
            ResourceMember.user_id == member_in.user_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this dataset"
        )
    
    # Create member
    member = ResourceMember(
        resource_type=ResourceType.DATASET,
        resource_id=dataset_id,
        user_id=member_in.user_id,
        role_id=member_in.role_id,
        created_by=current_user.id,
    )
    session.add(member)
    
    # Audit log
    log_member_add(
        session=session,
        resource_type=ResourceType.DATASET.value,
        resource_id=dataset_id,
        user_id=member_in.user_id,
        role_id=member_in.role_id,
        actor_id=current_user.id,
    )
    
    session.commit()
    session.refresh(member)
    
    return ResourceMemberRead(
        id=member.id,
        resource_type=member.resource_type,
        resource_id=member.resource_id,
        user_id=member.user_id,
        role_id=member.role_id,
        created_at=member.created_at,
        created_by=member.created_by,
        updated_at=member.updated_at,
        user_email=user.email,
        user_full_name=user.full_name,
        role_name=role.name,
        role_display_name=role.display_name,
    )


@router.put("/{dataset_id}/members/{user_id}", response_model=ResourceMemberRead)
def update_dataset_member_role(
    dataset_id: str,
    user_id: str,
    member_update: ResourceMemberUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_ASSIGN,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Update a member's role in a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    member = session.exec(
        select(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id,
            ResourceMember.user_id == user_id
        )
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this dataset"
        )
    
    # Check if new role exists and is a resource role
    new_role = session.get(Role, member_update.role_id)
    if not new_role:
        raise HTTPException(status_code=404, detail="Role not found")
    if new_role.type != RoleType.RESOURCE:
        raise HTTPException(
            status_code=400,
            detail="Must use a resource role for dataset membership"
        )
    
    # Cannot change owner role if user is the dataset owner
    if dataset.owner_id == user_id:
        owner_role = get_dataset_owner_role(session)
        if owner_role and member.role_id == owner_role.id:
            raise HTTPException(
                status_code=400,
                detail="Cannot change the role of the dataset owner"
            )
    
    old_role_id = member.role_id
    member.role_id = member_update.role_id
    member.updated_at = datetime.utcnow()
    session.add(member)
    
    # Audit log
    log_member_update(
        session=session,
        resource_type=ResourceType.DATASET.value,
        resource_id=dataset_id,
        user_id=user_id,
        old_role_id=old_role_id,
        new_role_id=member_update.role_id,
        actor_id=current_user.id,
    )
    
    session.commit()
    session.refresh(member)
    
    user = session.get(User, user_id)
    
    return ResourceMemberRead(
        id=member.id,
        resource_type=member.resource_type,
        resource_id=member.resource_id,
        user_id=member.user_id,
        role_id=member.role_id,
        created_at=member.created_at,
        created_by=member.created_by,
        updated_at=member.updated_at,
        user_email=user.email if user else None,
        user_full_name=user.full_name if user else None,
        role_name=new_role.name,
        role_display_name=new_role.display_name,
    )


@router.delete("/{dataset_id}/members/{user_id}")
def remove_dataset_member(
    dataset_id: str,
    user_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_ASSIGN,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Remove a member from a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    member = session.exec(
        select(ResourceMember).where(
            ResourceMember.resource_type == ResourceType.DATASET,
            ResourceMember.resource_id == dataset_id,
            ResourceMember.user_id == user_id
        )
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this dataset"
        )
    
    # Cannot remove the dataset owner
    if dataset.owner_id == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the dataset owner"
        )
    
    # Audit log
    log_member_remove(
        session=session,
        resource_type=ResourceType.DATASET.value,
        resource_id=dataset_id,
        user_id=user_id,
        role_id=member.role_id,
        actor_id=current_user.id,
    )
    
    session.delete(member)
    session.commit()
    
    return {"ok": True, "message": "Member removed from dataset"}


@router.get("/{dataset_id}/available-roles", response_model=List[dict])
def get_available_dataset_roles(
    dataset_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission(
        Permissions.DATASET_READ,
        ResourceType.DATASET,
        "dataset_id",
        get_dataset_owner
    )),
):
    """
    Get all available roles that can be assigned to dataset members.
    """
    # Get all resource roles
    roles = session.exec(
        select(Role).where(Role.type == RoleType.RESOURCE).order_by(Role.sort_order)
    ).all()
    
    return [
        {
            "id": role.id,
            "name": role.name,
            "displayName": role.display_name,
            "description": role.description,
        }
        for role in roles
    ]
