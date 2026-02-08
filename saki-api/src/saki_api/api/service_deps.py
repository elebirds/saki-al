"""
Service dependencies for FastAPI dependency injection.

Provides factory functions to create service instances with dependencies.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.db.session import get_session
from saki_api.repositories.role import RoleRepository
from saki_api.repositories.user import UserRepository
from saki_api.repositories.user_system_role import UserSystemRoleRepository
from saki_api.services.asset import AssetService
from saki_api.services.auth import AuthService
from saki_api.services.permission_query import PermissionQueryService
from saki_api.services.role import RoleService
from saki_api.services.system import SystemService
from saki_api.services.user import UserService
from saki_api.services.user_system_role import UserRoleService


# ============================================================================
# User Service Dependencies
# ============================================================================

def get_user_service(
        session: AsyncSession = Depends(get_session),
) -> UserService:
    """Get UserService with dependencies injected."""
    return UserService(session=session)


# Type alias for cleaner route signatures
UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# ============================================================================
# User Role Service Dependencies
# ============================================================================

def get_user_repository(
        session: AsyncSession = Depends(get_session),
) -> UserRepository:
    """Get UserRepository with dependencies injected."""
    return UserRepository(session)


def get_role_repository(
        session: AsyncSession = Depends(get_session),
) -> RoleRepository:
    """Get RoleRepository with dependencies injected."""
    return RoleRepository(session)


def get_user_role_repository(
        session: AsyncSession = Depends(get_session),
) -> UserSystemRoleRepository:
    """Get UserRoleRepository with dependencies injected."""
    return UserSystemRoleRepository(session)


def get_user_role_service(
        session: AsyncSession = Depends(get_session),
) -> UserRoleService:
    """Get UserRoleService with dependencies injected."""
    return UserRoleService(session=session)


# Type alias for cleaner route signatures
UserRoleServiceDep = Annotated[UserRoleService, Depends(get_user_role_service)]


# ============================================================================
# Role Service Dependencies
# ============================================================================

def get_role_service(
        session: AsyncSession = Depends(get_session),
) -> RoleService:
    """Get RoleService with dependencies injected."""
    return RoleService(session=session)


# Type alias for cleaner route signatures
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]


# ============================================================================
# System Service Dependencies
# ============================================================================

def get_system_service(
        session: AsyncSession = Depends(get_session),
) -> SystemService:
    return SystemService(session=session)


# Type alias for cleaner route signatures
SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]


# ============================================================================
# Auth Service Dependencies
# ============================================================================

def get_auth_service(
        session: AsyncSession = Depends(get_session),
) -> AuthService:
    return AuthService(session=session)


# Type alias for cleaner route signatures
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# ============================================================================
# Permission Query Service Dependencies
# ============================================================================

def get_permission_query_service(
        session: AsyncSession = Depends(get_session),
) -> PermissionQueryService:
    """Get PermissionQueryService with dependencies injected."""
    return PermissionQueryService(session=session)


PermissionQueryServiceDep = Annotated[PermissionQueryService, Depends(get_permission_query_service)]

# ============================================================================
# Dataset & Sample Service Dependencies
# ============================================================================

from saki_api.services.dataset import DatasetService
from saki_api.services.sample import SampleService


def get_dataset_service(
        session: AsyncSession = Depends(get_session),
) -> DatasetService:
    return DatasetService(session=session)


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]


def get_sample_service(
        session: AsyncSession = Depends(get_session),
) -> SampleService:
    return SampleService(session=session)


SampleServiceDep = Annotated[SampleService, Depends(get_sample_service)]


def get_asset_service(
        session: AsyncSession = Depends(get_session),
) -> AssetService:
    return AssetService(session=session)


AssetServiceDep = Annotated[AssetService, Depends(get_asset_service)]

# ============================================================================
# Project & Label Service Dependencies (L2 Layer)
# ============================================================================

from saki_api.services.project import ProjectService
from saki_api.services.label import LabelService


def get_project_service(
        session: AsyncSession = Depends(get_session),
) -> ProjectService:
    return ProjectService(session=session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def get_label_service(
        session: AsyncSession = Depends(get_session),
) -> LabelService:
    return LabelService(session=session)


LabelServiceDep = Annotated[LabelService, Depends(get_label_service)]

# ============================================================================
# Commit & Branch Service Dependencies (L2 Layer)
# ============================================================================

from saki_api.services.commit import CommitService
from saki_api.services.branch import BranchService


def get_commit_service(
        session: AsyncSession = Depends(get_session),
) -> CommitService:
    return CommitService(session=session)


CommitServiceDep = Annotated[CommitService, Depends(get_commit_service)]


def get_branch_service(
        session: AsyncSession = Depends(get_session),
) -> BranchService:
    return BranchService(session=session)


BranchServiceDep = Annotated[BranchService, Depends(get_branch_service)]

# ============================================================================
# Annotation Service Dependencies (L2 Layer)
# ============================================================================

from saki_api.services.annotation import AnnotationService
from saki_api.services.annotation_draft import AnnotationDraftService
from saki_api.services.annotation_working import AnnotationWorkingService
from saki_api.services.annotation_sync import AnnotationSyncService


def get_annotation_service(
        session: AsyncSession = Depends(get_session),
) -> AnnotationService:
    return AnnotationService(session=session)


AnnotationServiceDep = Annotated[AnnotationService, Depends(get_annotation_service)]


def get_annotation_draft_service(
        session: AsyncSession = Depends(get_session),
) -> AnnotationDraftService:
    return AnnotationDraftService(session=session)


AnnotationDraftServiceDep = Annotated[AnnotationDraftService, Depends(get_annotation_draft_service)]


def get_annotation_working_service() -> AnnotationWorkingService:
    return AnnotationWorkingService()


AnnotationWorkingServiceDep = Annotated[AnnotationWorkingService, Depends(get_annotation_working_service)]


def get_annotation_sync_service(
        session: AsyncSession = Depends(get_session),
) -> AnnotationSyncService:
    return AnnotationSyncService(session=session)


AnnotationSyncServiceDep = Annotated[AnnotationSyncService, Depends(get_annotation_sync_service)]

# ============================================================================
# Job Service Dependencies (L3 Layer)
# ============================================================================

from saki_api.services.job import JobService
from saki_api.services.model import ModelService
from saki_api.services.annotation_batch import AnnotationBatchService
from saki_api.services.runtime_observability import RuntimeObservabilityService


def get_job_service(
        session: AsyncSession = Depends(get_session),
) -> JobService:
    return JobService(session=session)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def get_model_service(
        session: AsyncSession = Depends(get_session),
) -> ModelService:
    return ModelService(session=session)


ModelServiceDep = Annotated[ModelService, Depends(get_model_service)]


def get_annotation_batch_service(
        session: AsyncSession = Depends(get_session),
) -> AnnotationBatchService:
    return AnnotationBatchService(session=session)


AnnotationBatchServiceDep = Annotated[AnnotationBatchService, Depends(get_annotation_batch_service)]


def get_runtime_observability_service(
        session: AsyncSession = Depends(get_session),
) -> RuntimeObservabilityService:
    return RuntimeObservabilityService(session=session)


RuntimeObservabilityServiceDep = Annotated[
    RuntimeObservabilityService,
    Depends(get_runtime_observability_service),
]
