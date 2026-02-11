"""
Project Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query

from saki_api.api.service_deps import ProjectServiceDep, AssetServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id, require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.models.enums import ProjectStatus
from saki_api.repositories.query import Pagination
from saki_api.schemas.pagination import PaginationResponse
from saki_api.schemas.dataset import DatasetRead
from saki_api.schemas.project import (
    ProjectCreate,
    ProjectDatasetLink,
    ProjectForkCreate,
    ProjectRead,
    ProjectReadMinimal,
    ProjectUpdate,
)
from saki_api.schemas.resource_member import (
    ResourceMemberCreateRequest,
    ResourceMemberRead,
    ResourceMemberUpdateRequest,
)
from saki_api.schemas.role import RoleReadMinimal
from saki_api.schemas.sample import ProjectSampleRead

router = APIRouter()


# =============================================================================
# Project CRUD Endpoints
# =============================================================================


@router.post("/", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_CREATE_ALL))
])
async def create_project(
        *,
        project_in: ProjectCreate,
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Create a new project with master branch and initial commit.

    This initializes the L2 layer for a project:
    - Creates the project
    - Links specified datasets
    - Creates initial commit (author_type=SYSTEM)
    - Creates master branch pointing to initial commit
    - Assigns creator as owner
    """
    project = await project_service.initialize_project(
        name=project_in.name,
        task_type=project_in.task_type,
        dataset_ids=project_in.dataset_ids,
        user_id=current_user_id,
        description=project_in.description,
        config=project_in.config,
    )

    # Get counts for response
    project_with_counts = await project_service.get_with_counts(project.id)

    return ProjectRead.model_validate(project_with_counts)


@router.get("/", response_model=PaginationResponse[ProjectRead])
async def list_projects(
        *,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        project_service: ProjectServiceDep,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
):
    """
    List all projects with pagination.
    """
    pagination = Pagination.from_page(page=page, limit=limit)
    result = await project_service.list_in_permission_paginated(
        user_id=current_user_id,
        pagination=pagination,
    )

    # Add counts to each project
    items_with_counts = []
    for project in result.items:
        counts = await project_service.repository.count_datasets(project.id)
        forks = await project_service.repository.count_forks(project.id)
        project_dict = {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "task_type": project.task_type,
            "status": project.status,
            "config": project.config,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "dataset_count": counts,
            "label_count": 0,
            "branch_count": 0,
            "commit_count": 0,
            "fork_count": forks,
        }
        items_with_counts.append(ProjectRead.model_validate(project_dict))

    response = PaginationResponse(
        items=items_with_counts,
        total=result.total,
        offset=result.offset,
        limit=result.limit,
        size=result.size,
        has_more=result.has_more,
    )

    return response


@router.get("/minimal", response_model=List[ProjectReadMinimal])
async def list_projects_minimal(
        *,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        project_service: ProjectServiceDep,
):
    """
    List all projects in minimal format (for dropdowns/selection).
    """
    return [
        ProjectReadMinimal(
            id=p.id,
            name=p.name,
            task_type=p.task_type,
            status=p.status,
        )
        for p in await project_service.list_in_permission(current_user_id)
    ]


@router.get("/{project_id}", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id"))
])
async def get_project(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Get a project by ID with aggregated counts.
    """
    project_with_counts = await project_service.get_with_counts(project_id)
    return ProjectRead.model_validate(project_with_counts)


@router.post("/{project_id}/fork", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_CREATE_ALL)),
    Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id")),
])
async def fork_project(
        *,
        project_id: uuid.UUID,
        payload: ProjectForkCreate,
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Fork a project by copying all branches, commits, labels and annotations.
    """
    forked = await project_service.fork_project(
        source_project_id=project_id,
        payload=payload,
        user_id=current_user_id,
    )
    project_with_counts = await project_service.get_with_counts(forked.id)
    return ProjectRead.model_validate(project_with_counts)


@router.put("/{project_id}", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_UPDATE, ResourceType.PROJECT, "project_id"))
])
async def update_project(
        *,
        project_id: uuid.UUID,
        project_in: ProjectUpdate,
        project_service: ProjectServiceDep,
):
    """
    Update a project.
    """
    await project_service.get_by_id_or_raise(project_id)
    project = await project_service.repository.update(
        project_id,
        project_in.model_dump(exclude_unset=True)
    )

    project_with_counts = await project_service.get_with_counts(project_id)
    return ProjectRead.model_validate(project_with_counts)


@router.post("/{project_id}:archive", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_ARCHIVE, ResourceType.PROJECT, "project_id"))
])
async def archive_project(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Archive a project.
    """
    await project_service.set_project_status(project_id, ProjectStatus.ARCHIVED)
    project_with_counts = await project_service.get_with_counts(project_id)
    return ProjectRead.model_validate(project_with_counts)


@router.post("/{project_id}:unarchive", response_model=ProjectRead, dependencies=[
    Depends(require_permission(Permissions.PROJECT_ARCHIVE, ResourceType.PROJECT, "project_id"))
])
async def unarchive_project(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Unarchive a project.
    """
    await project_service.set_project_status(project_id, ProjectStatus.ACTIVE)
    project_with_counts = await project_service.get_with_counts(project_id)
    return ProjectRead.model_validate(project_with_counts)


@router.delete("/{project_id}", response_model=None, dependencies=[
    Depends(require_permission(Permissions.PROJECT_DELETE, ResourceType.PROJECT, "project_id"))
])
async def delete_project(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Delete a project.

    Warning: This will cascade delete all branches, commits, and labels.
    """
    await project_service.get_by_id_or_raise(project_id)
    await project_service.repository.delete(project_id)


# =============================================================================
# Dataset Link Management Endpoints
# =============================================================================


@router.post("/{project_id}/datasets", response_model=List[uuid.UUID], dependencies=[
    Depends(require_permission(Permissions.PROJECT_UPDATE, ResourceType.PROJECT, "project_id"))
])
async def link_datasets(
        *,
        project_id: uuid.UUID,
        link: ProjectDatasetLink,
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Link datasets to a project.
    """
    links = await project_service.link_datasets(
        project_id=project_id,
        dataset_ids=link.dataset_ids,
        actor_user_id=current_user_id,
    )
    return [l.dataset_id for l in links]


@router.delete("/{project_id}/datasets", response_model=int, dependencies=[
    Depends(require_permission(Permissions.PROJECT_UPDATE, ResourceType.PROJECT, "project_id"))
])
async def unlink_datasets(
        *,
        project_id: uuid.UUID,
        link: ProjectDatasetLink,
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Unlink datasets from a project.
    """
    return await project_service.unlink_datasets(
        project_id=project_id,
        dataset_ids=link.dataset_ids,
        actor_user_id=current_user_id,
    )


@router.get("/{project_id}/datasets", response_model=List[uuid.UUID], dependencies=[
    Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id"))
])
async def get_linked_datasets(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Get all dataset IDs linked to a project.
    """
    dataset_ids = await project_service.get_linked_datasets(project_id)
    return dataset_ids


@router.get("/{project_id}/datasets/detail", response_model=List[DatasetRead], dependencies=[
    Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id"))
])
async def get_linked_dataset_details(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Get linked datasets in project scope without requiring dataset-level read permission.
    """
    return await project_service.get_linked_dataset_details(project_id)


# =============================================================================
# Project Sample Listing (with L2 status)
# =============================================================================


@router.get(
    "/{project_id}/datasets/{dataset_id}/samples",
    response_model=PaginationResponse[ProjectSampleRead],
    dependencies=[
        Depends(require_permission(Permissions.PROJECT_READ, ResourceType.PROJECT, "project_id"))
    ]
)
async def list_project_samples(
        *,
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        project_service: ProjectServiceDep,
        asset_service: AssetServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        branch_name: str = Query("master"),
        q: str | None = Query(None, description="Search by name or remark"),
        batch_id: uuid.UUID | None = Query(None, description="Filter by annotation batch"),
        status: str = Query("all", description="all|labeled|unlabeled|draft"),
        sort_by: str = Query("createdAt"),
        sort_order: str = Query("desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(24, ge=1, le=200),
):
    """
    List samples for a project dataset with annotation status.
    """
    page_data = await project_service.list_project_samples_page(
        project_id=project_id,
        dataset_id=dataset_id,
        current_user_id=current_user_id,
        branch_name=branch_name,
        q=q,
        batch_id=batch_id,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit,
    )

    items: list[ProjectSampleRead] = []
    for sample in page_data.samples:
        sample_dict = sample.model_dump() if hasattr(sample, 'model_dump') else sample.__dict__
        sample_read = ProjectSampleRead.model_validate(sample_dict)

        # Add presigned URL for primary asset if set
        if sample.primary_asset_id:
            try:
                primary_asset_url = await asset_service.get_presigned_download_url(sample.primary_asset_id)
                sample_read.primary_asset_url = primary_asset_url
            except Exception:
                pass

        count = page_data.annotation_counts.get(sample.id, 0)
        sample_read.annotation_count = count
        sample_read.is_labeled = count > 0
        sample_read.has_draft = sample.id in page_data.drafts_by_sample
        items.append(sample_read)

    return PaginationResponse.from_items(
        items=items,
        total=page_data.total,
        offset=page_data.offset,
        limit=page_data.limit,
    )


# =============================================================================
# Project Member Management Endpoints
# =============================================================================


@router.get("/{project_id}/members", response_model=List[ResourceMemberRead], dependencies=[
    Depends(require_permission(Permissions.PROJECT_ASSIGN, ResourceType.PROJECT, "project_id"))
])
async def get_project_members(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
):
    """
    Get all members of a project with user and role information.
    """
    members = await project_service.get_project_members(project_id)
    return members


@router.get("/{project_id}/available-roles", response_model=List[RoleReadMinimal], dependencies=[
    Depends(require_permission(Permissions.PROJECT_ASSIGN, ResourceType.PROJECT, "project_id"))
])
async def get_available_project_roles(
        *,
        project_id: uuid.UUID,
        project_service: ProjectServiceDep,
) -> List[RoleReadMinimal]:
    """
    Get available roles for project members.
    """
    roles = await project_service.get_available_project_roles(project_id)
    return [RoleReadMinimal.model_validate(role) for role in roles]


@router.post("/{project_id}/members", response_model=None, dependencies=[
    Depends(require_permission(Permissions.PROJECT_ASSIGN, ResourceType.PROJECT, "project_id"))
])
async def add_project_member(
        *,
        project_id: uuid.UUID,
        member: ResourceMemberCreateRequest,
        project_service: ProjectServiceDep,
):
    """
    Add a member to a project.

    Cannot assign owner role - owner is determined by project creator.
    """
    await project_service.add_project_member(project_id, member)


@router.put("/{project_id}/members/{user_id}", response_model=None, dependencies=[
    Depends(require_permission(Permissions.PROJECT_ASSIGN, ResourceType.PROJECT, "project_id"))
])
async def update_project_member(
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        member: ResourceMemberUpdateRequest,
        project_service: ProjectServiceDep,
):
    """
    Update a project member's role.

    Cannot assign owner role.
    """
    await project_service.update_project_member(project_id, user_id, member)


@router.delete("/{project_id}/members/{user_id}", response_model=None, dependencies=[
    Depends(require_permission(Permissions.PROJECT_ASSIGN, ResourceType.PROJECT, "project_id"))
])
async def remove_project_member(
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        project_service: ProjectServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Remove a member from a project.

    Cannot remove yourself.
    """
    await project_service.remove_project_member(project_id, user_id, current_user_id)
