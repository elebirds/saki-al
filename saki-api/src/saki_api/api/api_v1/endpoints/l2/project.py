"""
Project Endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, or_
from sqlmodel import select

from saki_api.api.service_deps import ProjectServiceDep, SampleServiceDep, AssetServiceDep
from saki_api.core.rbac.dependencies import get_current_user_id, require_permission
from saki_api.models import Permissions, ResourceType
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation_draft import AnnotationDraft
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.repositories.branch import BranchRepository
from saki_api.repositories.query import Pagination
from saki_api.schemas.pagination import PaginationResponse
from saki_api.schemas.project import (
    ProjectCreate,
    ProjectDatasetLink,
    ProjectRead,
    ProjectReadMinimal,
    ProjectUpdate,
)
from saki_api.schemas.sample import ProjectSampleRead
from saki_api.schemas.resource_member import (
    ResourceMemberCreateRequest,
    ResourceMemberRead,
    ResourceMemberUpdateRequest,
)

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


@router.get("/", response_model=PaginationResponse[ProjectRead], dependencies=[
    Depends(require_permission(Permissions.PROJECT_READ_ALL))
])
async def list_projects(
        *,
        project_service: ProjectServiceDep,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=200),
):
    """
    List all projects with pagination.
    """
    pagination = Pagination.from_page(page=page, limit=limit)
    result = await project_service.list_paginated(pagination)

    # Add counts to each project
    items_with_counts = []
    for project in result.items:
        counts = await project_service.repository.count_datasets(project.id)
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


@router.get("/minimal", response_model=List[ProjectReadMinimal], dependencies=[
    Depends(require_permission(Permissions.PROJECT_READ_ALL))
])
async def list_projects_minimal(
        *,
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
        for p in await project_service.list()
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
):
    """
    Link datasets to a project.
    """
    links = await project_service.link_datasets(project_id, link.dataset_ids)
    return [l.dataset_id for l in links]


@router.delete("/{project_id}/datasets", response_model=int, dependencies=[
    Depends(require_permission(Permissions.PROJECT_UPDATE, ResourceType.PROJECT, "project_id"))
])
async def unlink_datasets(
        *,
        project_id: uuid.UUID,
        link: ProjectDatasetLink,
        project_service: ProjectServiceDep,
):
    """
    Unlink datasets from a project.
    """
    return await project_service.unlink_datasets(project_id, link.dataset_ids)


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
        sample_service: SampleServiceDep,
        asset_service: AssetServiceDep,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        branch_name: str = Query("master"),
        q: str | None = Query(None, description="Search by name or remark"),
        status: str = Query("all", description="all|labeled|unlabeled|draft"),
        sort_by: str = Query("createdAt"),
        sort_order: str = Query("desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(24, ge=1, le=200),
):
    """
    List samples for a project dataset with annotation status.
    """
    # Ensure dataset is linked to project
    dataset_ids = await project_service.get_linked_datasets(project_id)
    if dataset_id not in dataset_ids:
        return PaginationResponse.from_items(items=[], total=0, offset=0, limit=limit)

    branch_repo = BranchRepository(sample_service.session)
    branch = await branch_repo.get_by_name(project_id, branch_name)
    if not branch:
        return PaginationResponse.from_items(items=[], total=0, offset=0, limit=limit)

    head_commit_id = branch.head_commit_id

    # Build base query
    statement = select(Sample).where(Sample.dataset_id == dataset_id)
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(
                Sample.name.ilike(pattern),
                Sample.remark.ilike(pattern),
            )
        )

    # Status filter
    labeled_subq = select(CommitAnnotationMap.sample_id).where(
        CommitAnnotationMap.commit_id == head_commit_id
    ).distinct()

    if status == "labeled":
        statement = statement.where(Sample.id.in_(labeled_subq))
    elif status == "unlabeled":
        statement = statement.where(~Sample.id.in_(labeled_subq))
    elif status == "draft":
        draft_subq = select(AnnotationDraft.sample_id).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == current_user_id,
            AnnotationDraft.branch_name == branch_name,
        ).distinct()
        statement = statement.where(Sample.id.in_(draft_subq))

    # Sorting
    sort_map = {
        "name": Sample.name,
        "createdAt": Sample.created_at,
        "updatedAt": Sample.updated_at,
        "created_at": Sample.created_at,
        "updated_at": Sample.updated_at,
    }
    sort_column = sort_map.get(sort_by, Sample.created_at)
    order_clause = asc(sort_column) if sort_order == "asc" else desc(sort_column)
    statement = statement.order_by(order_clause)

    # Pagination
    pagination = Pagination.from_page(page=page, limit=limit)
    count_stmt = select(func.count()).select_from(statement.subquery())
    total_result = await sample_service.session.exec(count_stmt)
    total = total_result.one() or 0
    if isinstance(total, (list, tuple)):
        total = total[0]

    result = await sample_service.session.exec(
        statement.offset(pagination.offset).limit(pagination.limit)
    )
    samples = result.all()

    # Annotation counts for current page
    sample_ids = [s.id for s in samples]
    annotation_counts: dict[uuid.UUID, int] = {}
    if sample_ids:
        count_statement = (
            select(
                CommitAnnotationMap.sample_id,
                func.count(CommitAnnotationMap.annotation_id),
            )
            .where(
                CommitAnnotationMap.commit_id == head_commit_id,
                CommitAnnotationMap.sample_id.in_(sample_ids),
            )
            .group_by(CommitAnnotationMap.sample_id)
        )
        count_result = await sample_service.session.exec(count_statement)
        for sample_id, count in count_result.all():
            annotation_counts[sample_id] = count

    # Draft status for current page
    drafts_by_sample: set[uuid.UUID] = set()
    if sample_ids:
        draft_statement = select(AnnotationDraft.sample_id).where(
            AnnotationDraft.project_id == project_id,
            AnnotationDraft.user_id == current_user_id,
            AnnotationDraft.branch_name == branch_name,
            AnnotationDraft.sample_id.in_(sample_ids),
        )
        draft_result = await sample_service.session.exec(draft_statement)
        drafts_by_sample = {
            row[0] if isinstance(row, (list, tuple)) else row
            for row in draft_result.all()
        }

    items: list[ProjectSampleRead] = []
    for sample in samples:
        sample_dict = sample.model_dump() if hasattr(sample, 'model_dump') else sample.__dict__
        sample_read = ProjectSampleRead.model_validate(sample_dict)

        # Add presigned URL for primary asset if set
        if sample.primary_asset_id:
            try:
                primary_asset_url = await asset_service.get_presigned_download_url(sample.primary_asset_id)
                sample_read.primary_asset_url = primary_asset_url
            except Exception:
                pass

        count = annotation_counts.get(sample.id, 0)
        sample_read.annotation_count = count
        sample_read.is_labeled = count > 0
        sample_read.has_draft = sample.id in drafts_by_sample
        items.append(sample_read)

    return PaginationResponse.from_items(
        items=items,
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
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
