"""
Runtime executor observability endpoints.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import get_runtime_observability_service
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.api.runtime_executor import (
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimePluginCatalogResponse,
)
from saki_api.modules.runtime.service.observability.runtime_observability_service import (
    RuntimeObservabilityService,
)
from saki_api.modules.shared.modeling import Permissions, ResourceType

router = APIRouter()


async def _ensure_runtime_read_permission(session: AsyncSession, current_user_id: uuid.UUID) -> None:
    checker = PermissionChecker(session)
    if await checker.check(user_id=current_user_id, permission=Permissions.ROUND_READ):
        return
    if await checker.check(user_id=current_user_id, permission=Permissions.PROJECT_READ_ALL):
        return

    # 允许具备任一项目 ROUND_READ 资源级权限的用户访问运行时统计入口
    accessible_project_ids = await checker.resource_member_repo.get_resource_ids_by_user_with_permission(
        user_id=current_user_id,
        resource_type=ResourceType.PROJECT,
        required_permission=Permissions.ROUND_READ,
    )
    if accessible_project_ids:
        return

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
