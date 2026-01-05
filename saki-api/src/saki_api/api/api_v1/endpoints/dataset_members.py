"""
API endpoints for Dataset member management.

Allows managing users' roles and permissions for specific datasets.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from saki_api.api import deps
from saki_api.core.permissions import require_permission
from saki_api.db.session import get_session
from saki_api.models.dataset import Dataset
from saki_api.models.permission import (
    Permission, ResourceRole,
    DatasetMember, DatasetMemberCreate, DatasetMemberRead, DatasetMemberUpdate
)
from saki_api.models.user import User
from sqlmodel import Session, select

router = APIRouter()


@router.get("/{dataset_id}/members", response_model=List[DatasetMemberRead])
def get_dataset_members(
        dataset_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permission.DATASET_READ, "dataset", "dataset_id"
        ))
):
    """
    Get all members of a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    members = session.exec(
        select(DatasetMember).where(DatasetMember.dataset_id == dataset_id)
    ).all()

    result = []
    for member in members:
        user = session.get(User, member.user_id)
        result.append(DatasetMemberRead(
            dataset_id=member.dataset_id,
            user_id=member.user_id,
            role=member.role,
            created_at=member.created_at,
            created_by=member.created_by,
            user_email=user.email if user else None,
            user_full_name=user.full_name if user else None,
        ))

    return result


@router.post("/{dataset_id}/members", response_model=DatasetMemberRead)
def add_dataset_member(
        dataset_id: str,
        member_data: DatasetMemberCreate,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permission.DATASET_MANAGE_MEMBERS, "dataset", "dataset_id"
        ))
):
    """
    Add a member to a dataset with a specific role.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Check if user exists
    user = session.get(User, member_data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if member already exists
    existing = session.exec(
        select(DatasetMember).where(
            DatasetMember.dataset_id == dataset_id,
            DatasetMember.user_id == member_data.user_id
        )
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this dataset"
        )

    # Create member
    member = DatasetMember(
        dataset_id=dataset_id,
        user_id=member_data.user_id,
        role=member_data.role,
        created_by=current_user.id,
    )
    session.add(member)
    session.commit()
    session.refresh(member)

    return DatasetMemberRead(
        dataset_id=member.dataset_id,
        user_id=member.user_id,
        role=member.role,
        created_at=member.created_at,
        created_by=member.created_by,
        user_email=user.email,
        user_full_name=user.full_name,
    )


@router.put("/{dataset_id}/members/{user_id}", response_model=DatasetMemberRead)
def update_dataset_member_role(
        dataset_id: str,
        user_id: str,
        member_update: DatasetMemberUpdate,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permission.DATASET_MANAGE_MEMBERS, "dataset", "dataset_id"
        ))
):
    """
    Update a member's role in a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    member = session.exec(
        select(DatasetMember).where(
            DatasetMember.dataset_id == dataset_id,
            DatasetMember.user_id == user_id
        )
    ).first()

    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this dataset"
        )

    member.role = member_update.role
    session.add(member)
    session.commit()
    session.refresh(member)

    user = session.get(User, user_id)
    return DatasetMemberRead(
        dataset_id=member.dataset_id,
        user_id=member.user_id,
        role=member.role,
        created_at=member.created_at,
        created_by=member.created_by,
        user_email=user.email if user else None,
        user_full_name=user.full_name if user else None,
    )


@router.delete("/{dataset_id}/members/{user_id}")
def remove_dataset_member(
        dataset_id: str,
        user_id: str,
        session: Session = Depends(get_session),
        current_user: User = Depends(require_permission(
            Permission.DATASET_MANAGE_MEMBERS, "dataset", "dataset_id"
        ))
):
    """
    Remove a member from a dataset.
    """
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    member = session.exec(
        select(DatasetMember).where(
            DatasetMember.dataset_id == dataset_id,
            DatasetMember.user_id == user_id
        )
    ).first()

    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this dataset"
        )

    # Prevent removing the owner
    if dataset.owner_id == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the dataset owner"
        )

    session.delete(member)
    session.commit()

    return {"ok": True, "message": "Member removed from dataset"}
