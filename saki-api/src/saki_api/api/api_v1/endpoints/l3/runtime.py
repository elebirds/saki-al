"""
Runtime executor observability endpoints.
"""

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.api.service_deps import get_runtime_observability_service
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.core.rbac.checker import PermissionChecker
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.db.session import get_session
from saki_api.models import Permissions
from saki_api.schemas.l3.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimePluginCatalogResponse,
)
from saki_api.services.runtime_observability import RuntimeObservabilityService

router = APIRouter()


async def _ensure_runtime_read_permission(session: AsyncSession, current_user_id: str) -> None:
    checker = PermissionChecker(session)
    allowed = await checker.check(user_id=current_user_id, permission=Permissions.JOB_READ)
    if not allowed:
        allowed = await checker.check(user_id=current_user_id, permission=Permissions.PROJECT_READ_ALL)
    if not allowed:
        raise ForbiddenAppException("Permission denied: runtime:read")


def _resolve_runtime_observability_service(
        *,
        session: AsyncSession,
        runtime_observability_service: RuntimeObservabilityService | object,
) -> RuntimeObservabilityService:
    if isinstance(runtime_observability_service, RuntimeObservabilityService):
        return runtime_observability_service
    return RuntimeObservabilityService(session=session)


@router.get("/runtime/executors", response_model=RuntimeExecutorListResponse)
async def list_runtime_executors(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    return await service.list_executors()


@router.get("/runtime/executors/stats", response_model=RuntimeExecutorStatsResponse)
async def get_runtime_executor_stats(
        range: RuntimeExecutorStatsRange = "30m",
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    return await service.get_executor_stats(range)


@router.get("/runtime/executors/{executor_id}", response_model=RuntimeExecutorRead)
async def get_runtime_executor(
        *,
        executor_id: str,
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    return await service.get_executor(executor_id)


@router.get("/runtime/plugins", response_model=RuntimePluginCatalogResponse)
async def list_runtime_plugins(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    return await service.list_plugins()
