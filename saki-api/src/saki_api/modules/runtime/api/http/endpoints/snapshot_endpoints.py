"""Loop snapshot/gate query endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import RuntimeServiceDep
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.runtime.api.http.support.loop_control_helpers import ensure_loop_project_perm
from saki_api.modules.runtime.api.round_step import (
    LoopGateResponse,
    LoopSnapshotRead,
    SnapshotVersionRead,
    SnapshotVersionSummaryRead,
)

router = APIRouter()


@router.get("/loops/{loop_id}/snapshot", response_model=LoopSnapshotRead)
async def get_loop_snapshot(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    payload = await runtime_service.get_loop_snapshot(loop_id=loop_id)
    active = payload.get("active")
    history = payload.get("history") or []
    return LoopSnapshotRead(
        loop_id=payload["loop_id"],
        active_snapshot_version_id=payload.get("active_snapshot_version_id"),
        active=SnapshotVersionRead.model_validate(active, from_attributes=True) if active else None,
        history=[SnapshotVersionSummaryRead.model_validate(item, from_attributes=True) for item in history],
        primary_view=payload.get("primary_view") or {},
        advanced_view=payload.get("advanced_view") or {},
    )


@router.get("/loops/{loop_id}/gate", response_model=LoopGateResponse)
async def get_loop_gate(
    *,
    loop_id: uuid.UUID,
    runtime_service: RuntimeServiceDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_READ,
    )
    payload = await runtime_service.get_loop_gate(loop_id=loop_id)
    return LoopGateResponse(**payload)
