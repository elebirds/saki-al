"""
Commit Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends

from saki_api.api.service_deps import CommitServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id, require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.schemas.commit import CommitCreate, CommitDiff, CommitHistoryItem, CommitRead, CommitTree

router = APIRouter()


# =============================================================================
# Commit CRUD Endpoints
# =============================================================================


@router.get("/projects/{project_id}/commits", response_model=List[CommitHistoryItem], dependencies=[
    Depends(require_permission(Permissions.COMMIT_READ, ResourceType.PROJECT, "project_id"))
])
async def list_commits(
        *,
        project_id: uuid.UUID,
        commit_service: CommitServiceDep,
):
    """
    Get all commits for a project, newest first.
    """
    commits = await commit_service.get_project_commits(project_id)
    return [
        CommitHistoryItem(
            id=c.id,
            message=c.message,
            author_type=c.author_type,
            author_id=c.author_id,
            parent_id=c.parent_id,
            created_at=c.created_at,
            stats=c.stats,
        )
        for c in commits
    ]


@router.get("/projects/{project_id}/commits/tree", response_model=List[CommitTree], dependencies=[
    Depends(require_permission(Permissions.COMMIT_READ, ResourceType.PROJECT, "project_id"))
])
async def get_commit_tree(
        *,
        project_id: uuid.UUID,
        commit_service: CommitServiceDep,
):
    """
    Get the full commit history as a tree structure.
    """
    return await commit_service.get_commit_tree(project_id)


@router.get("/commits/{commit_id}", response_model=CommitRead, dependencies=[
    Depends(require_permission(Permissions.COMMIT_READ))
])
async def get_commit(
        *,
        commit_id: uuid.UUID,
        commit_service: CommitServiceDep,
):
    """
    Get a commit by ID.
    """
    commit = await commit_service.get_by_id_or_raise(commit_id)
    return CommitRead.model_validate(commit)


@router.get("/commits/{commit_id}/history", response_model=List[CommitHistoryItem], dependencies=[
    Depends(require_permission(Permissions.COMMIT_READ))
])
async def get_commit_history(
        *,
        commit_id: uuid.UUID,
        depth: int = 100,
        commit_service: CommitServiceDep,
):
    """
    Get commit history by following parent_id chain.

    Returns commits from oldest to newest.
    """
    return await commit_service.get_history(commit_id, depth)


@router.get("/commits/{commit_id}/diff", response_model=CommitDiff, dependencies=[
    Depends(require_permission(Permissions.COMMIT_READ))
])
async def get_commit_diff(
        *,
        commit_id: uuid.UUID,
        compare_with_id: uuid.UUID | None = None,
        commit_service: CommitServiceDep,
):
    """
    Compare two commits and return the differences.

    If compare_with_id is not provided, compares with parent commit.
    """
    if compare_with_id is None:
        # Compare with parent
        commit = await commit_service.get_by_id_or_raise(commit_id)
        compare_with_id = commit.parent_id

    if not compare_with_id:
        # Root commit, no diff
        diff = CommitDiff(
            from_commit_id=commit_id,
            to_commit_id=commit_id,
            added_samples=[],
            removed_samples=[],
            modified_annotations={},
        )
    else:
        diff = await commit_service.get_commits_diff(compare_with_id, commit_id)

    return diff


@router.post("/projects/{project_id}/commits", response_model=CommitRead, dependencies=[
    Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id"))
])
async def create_commit(
        *,
        project_id: uuid.UUID,
        commit_in: CommitCreate,
        commit_service: CommitServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Create a new commit.

    Note: This is typically called automatically during annotation save workflow.
    Direct commit creation is mainly for system operations.
    """
    commit = await commit_service.create_commit(
        project_id=project_id,
        message=commit_in.message,
        parent_id=commit_in.parent_id,
        author_type=commit_in.author_type,
        author_id=commit_in.author_id or current_user_id,
        stats=commit_in.stats,
    )
    return CommitRead.model_validate(commit)
