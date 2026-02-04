"""
Branch Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from saki_api.api.service_deps import BranchServiceDep
from saki_api.core.rbac.dependencies import require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.schemas.branch import BranchRead, BranchReadMinimal, BranchSwitch

router = APIRouter()


# =============================================================================
# Branch CRUD Endpoints
# =============================================================================


@router.get("/projects/{project_id}/branches", response_model=List[dict], dependencies=[
    Depends(require_permission(Permissions.BRANCH_READ, ResourceType.PROJECT, "project_id"))
])
async def list_branches(
        *,
        project_id: uuid.UUID,
        branch_service: BranchServiceDep,
):
    """
    Get all branches for a project with HEAD commit info.
    """
    return await branch_service.get_project_branches_with_head(project_id)


@router.get("/projects/{project_id}/branches/minimal", response_model=List[BranchReadMinimal],
            dependencies=[
                Depends(require_permission(Permissions.BRANCH_READ, ResourceType.PROJECT, "project_id"))
            ])
async def list_branches_minimal(
        *,
        project_id: uuid.UUID,
        branch_service: BranchServiceDep,
):
    """
    Get all branches for a project in minimal format (for dropdowns).
    """
    branches = await branch_service.get_project_branches(project_id)
    return [
        BranchReadMinimal(
            id=b.id,
            name=b.name,
            head_commit_id=b.head_commit_id,
            is_protected=b.is_protected,
        )
        for b in branches
    ]


@router.get("/branches/{branch_id}", response_model=BranchRead, dependencies=[
    Depends(require_permission(Permissions.BRANCH_READ))
])
async def get_branch(
        *,
        branch_id: uuid.UUID,
        branch_service: BranchServiceDep,
):
    """
    Get a branch by ID.
    """
    branch = await branch_service.get_by_id_or_raise(branch_id)
    return BranchRead.model_validate(branch)


@router.get("/projects/{project_id}/branches/master", response_model=BranchRead, dependencies=[
    Depends(require_permission(Permissions.BRANCH_READ, ResourceType.PROJECT, "project_id"))
])
async def get_master_branch(
        *,
        project_id: uuid.UUID,
        branch_service: BranchServiceDep,
):
    """
    Get the master branch for a project.
    """
    branch = await branch_service.get_master_branch(project_id)
    return BranchRead.model_validate(branch)


# =============================================================================
# Branch Management
# =============================================================================


@router.post("/projects/{project_id}/branches", response_model=BranchRead, dependencies=[
    Depends(require_permission(Permissions.BRANCH_MANAGE, ResourceType.PROJECT, "project_id"))
])
async def create_branch(
        *,
        project_id: uuid.UUID,
        name: str = Query(..., description="Branch name"),
        from_commit_id: uuid.UUID = Query(..., description="Commit to branch from"),
        description: str | None = Query(None, description="Optional branch description"),
        branch_service: BranchServiceDep,
):
    """
    Create a new branch from a commit.

    Creates a new branch pointing to the specified commit.
    """
    branch = await branch_service.create_branch(
        project_id=project_id,
        name=name,
        from_commit_id=from_commit_id,
        description=description,
    )
    return BranchRead.model_validate(branch)


@router.post("/branches/{branch_id}/switch", response_model=BranchRead, dependencies=[
    Depends(require_permission(Permissions.BRANCH_SWITCH))
])
async def switch_branch(
        *,
        branch_id: uuid.UUID,
        switch: BranchSwitch,
        branch_service: BranchServiceDep,
):
    """
    Move branch HEAD to a different commit (git checkout equivalent).

    Cannot modify protected branches.
    """
    branch = await branch_service.switch_to_commit(branch_id, switch.target_commit_id)
    return BranchRead.model_validate(branch)


@router.put("/branches/{branch_id}", response_model=BranchRead, dependencies=[
    Depends(require_permission(Permissions.BRANCH_MANAGE))
])
async def update_branch(
        *,
        branch_id: uuid.UUID,
        name: str | None = Query(None, description="New branch name"),
        description: str | None = Query(None, description="New branch description"),
        is_protected: bool | None = Query(None, description="New protected status"),
        branch_service: BranchServiceDep,
):
    """
    Update branch metadata (name, description, protected status).

    Note: Use switch_branch to change HEAD commit.
    """
    branch = await branch_service.update_branch(
        branch_id=branch_id,
        name=name,
        description=description,
        is_protected=is_protected,
    )
    return BranchRead.model_validate(branch)


@router.delete("/branches/{branch_id}", response_model=None, dependencies=[
    Depends(require_permission(Permissions.BRANCH_MANAGE))
])
async def delete_branch(
        *,
        branch_id: uuid.UUID,
        branch_service: BranchServiceDep,
):
    """
    Delete a branch.

    Cannot delete protected branches.
    """
    await branch_service.delete_branch(branch_id)
