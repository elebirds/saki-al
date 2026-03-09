"""
Runtime executor observability endpoints.
"""

import uuid
import asyncio
from sqlmodel import select

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import (
    DispatcherAdminClientDep,
    get_runtime_release_service,
    get_runtime_observability_service,
)
from saki_api.core.exceptions import ForbiddenAppException, InternalServerErrorAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.api.runtime_executor import (
    RuntimeDomainCommandResponse,
    RuntimeDomainStatusResponse,
    RuntimeDesiredStatePatchRequest,
    RuntimeDesiredStateResponse,
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    RuntimePluginCatalogResponse,
    RuntimeReleaseListResponse,
    RuntimeReleaseRead,
    RuntimeUpdateAttemptListResponse,
)
from saki_api.modules.runtime.service.observability.runtime_observability_service import (
    RuntimeObservabilityService,
)
from saki_api.modules.runtime.service.release.runtime_release_service import RuntimeReleaseService
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.shared.modeling.enums import LoopLifecycle, LoopPauseReason

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


async def _ensure_runtime_manage_permission(session: AsyncSession, current_user_id: uuid.UUID) -> None:
    checker = PermissionChecker(session)
    if await checker.check(user_id=current_user_id, permission=Permissions.ROUND_MANAGE_ALL):
        return
    if await checker.check(user_id=current_user_id, permission=Permissions.LOOP_MANAGE_ALL):
        return
    raise ForbiddenAppException("Permission denied: runtime:manage")


def _resolve_runtime_observability_service(
        *,
        session: AsyncSession,
        runtime_observability_service: RuntimeObservabilityService | object,
) -> RuntimeObservabilityService:
    if isinstance(runtime_observability_service, RuntimeObservabilityService):
        return runtime_observability_service
    return RuntimeObservabilityService(session=session)


def _resolve_runtime_release_service(
        runtime_release_service: RuntimeReleaseService | object,
        *,
        session: AsyncSession,
) -> RuntimeReleaseService:
    if isinstance(runtime_release_service, RuntimeReleaseService):
        return runtime_release_service
    return RuntimeReleaseService(session=session)


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


@router.post("/runtime/releases", response_model=RuntimeReleaseRead)
async def create_runtime_release(
        *,
        file: UploadFile = File(..., description="tar.gz release archive"),
        runtime_release_service: RuntimeReleaseService | object = Depends(get_runtime_release_service),
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_release_service(runtime_release_service, session=session)
    return await service.create_release(file=file, current_user_id=current_user_id)


@router.get("/runtime/releases", response_model=RuntimeReleaseListResponse)
async def list_runtime_releases(
        *,
        component_type: str | None = Query(default=None),
        component_name: str | None = Query(default=None),
        runtime_release_service: RuntimeReleaseService | object = Depends(get_runtime_release_service),
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_release_service(runtime_release_service, session=session)
    return await service.list_releases(component_type=component_type, component_name=component_name)


@router.get("/runtime/desired-state", response_model=RuntimeDesiredStateResponse)
async def get_runtime_desired_state(
        *,
        runtime_release_service: RuntimeReleaseService | object = Depends(get_runtime_release_service),
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_release_service(runtime_release_service, session=session)
    return await service.list_desired_state()


@router.patch("/runtime/desired-state", response_model=RuntimeDesiredStateResponse)
async def patch_runtime_desired_state(
        *,
        payload: RuntimeDesiredStatePatchRequest,
        runtime_release_service: RuntimeReleaseService | object = Depends(get_runtime_release_service),
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_release_service(runtime_release_service, session=session)
    return await service.set_desired_state(items=payload.items, current_user_id=current_user_id)


@router.get("/runtime/update-attempts", response_model=RuntimeUpdateAttemptListResponse)
async def list_runtime_update_attempts(
        *,
        executor_id: str | None = Query(default=None),
        component_type: str | None = Query(default=None),
        component_name: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        runtime_release_service: RuntimeReleaseService | object = Depends(get_runtime_release_service),
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_read_permission(session, current_user_id)
    service = _resolve_runtime_release_service(runtime_release_service, session=session)
    return await service.list_update_attempts(
        executor_id=executor_id,
        component_type=component_type,
        component_name=component_name,
        limit=limit,
    )


@router.get("/runtime/domain/status", response_model=RuntimeDomainStatusResponse)
async def get_runtime_domain_status(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    return await service.get_runtime_domain_status()


@router.post("/runtime/domain:connect", response_model=RuntimeDomainCommandResponse)
async def connect_runtime_domain(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    try:
        return await service.set_runtime_domain_enabled(True)
    except RuntimeError as exc:
        raise InternalServerErrorAppException(str(exc)) from exc


@router.post("/runtime/domain:disconnect", response_model=RuntimeDomainCommandResponse)
async def disconnect_runtime_domain(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    try:
        return await service.set_runtime_domain_enabled(False)
    except RuntimeError as exc:
        raise InternalServerErrorAppException(str(exc)) from exc


@router.post("/runtime/domain:reconnect", response_model=RuntimeDomainCommandResponse)
async def reconnect_runtime_domain(
        session: AsyncSession = Depends(get_session),
        runtime_observability_service: RuntimeObservabilityService | object = Depends(
            get_runtime_observability_service
        ),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    service = _resolve_runtime_observability_service(
        session=session,
        runtime_observability_service=runtime_observability_service,
    )
    try:
        return await service.reconnect_runtime_domain()
    except RuntimeError as exc:
        raise InternalServerErrorAppException(str(exc)) from exc


@router.post("/runtime/loops:resume-maintenance-paused", response_model=RuntimeDomainCommandResponse)
async def resume_maintenance_paused_loops(
        dispatcher_admin_client: DispatcherAdminClientDep,
        session: AsyncSession = Depends(get_session),
        current_user_id=Depends(get_current_user_id),
):
    await _ensure_runtime_manage_permission(session, current_user_id)
    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher admin client is not enabled")

    loop_ids = list(
        (
            await session.exec(
                select(Loop.id).where(
                    Loop.lifecycle == LoopLifecycle.PAUSED,
                    Loop.pause_reason == LoopPauseReason.MAINTENANCE,
                )
            )
        ).all()
    )
    responses = await asyncio.gather(
        *(dispatcher_admin_client.resume_loop(str(loop_id)) for loop_id in loop_ids),
        return_exceptions=True,
    )
    resumed = sum(1 for item in responses if not isinstance(item, Exception) and str(item.status or "") == "applied")
    failed = sum(1 for item in responses if isinstance(item, Exception) or str(getattr(item, "status", "")) != "applied")
    return RuntimeDomainCommandResponse(
        command_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        status="ok" if failed == 0 else "partial",
        message=f"resumed {resumed}/{len(loop_ids)} maintenance-paused loops",
    )
