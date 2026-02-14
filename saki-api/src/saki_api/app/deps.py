"""
Service dependencies for FastAPI dependency injection.

Provides factory functions to create service instances with dependencies.
"""

from typing import Annotated, AsyncIterator

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.session import get_session
from saki_api.core.config import settings
from saki_api.infra.dispatcher_admin.client import DispatcherAdminClient
from saki_api.modules.access.service.auth import AuthService
from saki_api.modules.access.service.permission_query import PermissionQueryService
from saki_api.modules.access.service.role import RoleService
from saki_api.modules.access.service.user import UserService
from saki_api.modules.access.service.user_system_role import UserRoleService
from saki_api.modules.storage.service.asset import AssetService
from saki_api.modules.system.service.system import SystemService
from saki_api.modules.system.service.system_settings import SystemSettingsService


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


def get_system_settings_service(
        session: AsyncSession = Depends(get_session),
) -> SystemSettingsService:
    return SystemSettingsService(session=session)


SystemSettingsServiceDep = Annotated[SystemSettingsService, Depends(get_system_settings_service)]


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

from saki_api.modules.project.service.dataset import DatasetService
from saki_api.modules.project.service.sample import SampleService


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

from saki_api.modules.project.service.project import ProjectService
from saki_api.modules.project.service.label import LabelService


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

from saki_api.modules.project.service.commit import CommitService
from saki_api.modules.project.service.branch import BranchService


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

from saki_api.modules.annotation.service.annotation import AnnotationService
from saki_api.modules.annotation.service.draft import AnnotationDraftService
from saki_api.modules.annotation.service.working import AnnotationWorkingService
from saki_api.modules.annotation.service.sync import AnnotationSyncService


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
# Runtime Service Dependencies (L3 Layer)
# ============================================================================

from saki_api.modules.runtime.service.runtime_service import RuntimeService
from saki_api.modules.runtime.service.modeling.model_registry_service import ModelService
from saki_api.modules.runtime.service.observability.runtime_observability_service import (
    RuntimeObservabilityService,
)


def get_runtime_service(
        session: AsyncSession = Depends(get_session),
) -> RuntimeService:
    return RuntimeService(session=session)


RuntimeServiceDep = Annotated[RuntimeService, Depends(get_runtime_service)]


def get_model_service(
        session: AsyncSession = Depends(get_session),
) -> ModelService:
    return ModelService(session=session)


ModelServiceDep = Annotated[ModelService, Depends(get_model_service)]


async def get_dispatcher_admin_client() -> AsyncIterator[DispatcherAdminClient]:
    client = DispatcherAdminClient(
        target=settings.DISPATCHER_ADMIN_TARGET,
        internal_token=settings.INTERNAL_TOKEN,
        timeout_sec=settings.DISPATCHER_ADMIN_TIMEOUT_SEC,
    )
    try:
        yield client
    finally:
        await client.close()


DispatcherAdminClientDep = Annotated[DispatcherAdminClient, Depends(get_dispatcher_admin_client)]


def get_runtime_observability_service(
        session: AsyncSession = Depends(get_session),
        dispatcher_admin_client: DispatcherAdminClient = Depends(get_dispatcher_admin_client),
) -> RuntimeObservabilityService:
    return RuntimeObservabilityService(session=session, dispatcher_admin_client=dispatcher_admin_client)


RuntimeObservabilityServiceDep = Annotated[
    RuntimeObservabilityService,
    Depends(get_runtime_observability_service),
]
