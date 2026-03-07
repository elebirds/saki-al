"""Shared helpers for loop control endpoint modules."""

from __future__ import annotations

import uuid

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep
from saki_api.core.exceptions import BadRequestAppException, InternalServerErrorAppException
from saki_api.modules.runtime.api.http.support.project_permission import ensure_project_permission
from saki_api.modules.runtime.api.round_step import PredictionRead, PredictionTaskRead


async def ensure_loop_project_perm(
    *,
    session: AsyncSession,
    current_user_id: uuid.UUID,
    project_id: uuid.UUID,
    required: str,
) -> None:
    await ensure_project_permission(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required_permission=required,
    )


async def dispatch_loop_command(
    *,
    command: str,
    loop_id: uuid.UUID,
    round_id: uuid.UUID | None = None,
    reason: str = "",
    force: bool = False,
    dispatcher_admin_client: DispatcherAdminClientDep,
) -> object:
    if not dispatcher_admin_client.enabled:
        raise InternalServerErrorAppException("dispatcher_admin 未配置")

    loop_id_text = str(loop_id)
    try:
        if command == "start":
            return await dispatcher_admin_client.start_loop(loop_id_text)
        if command == "pause":
            return await dispatcher_admin_client.pause_loop(loop_id_text)
        if command == "resume":
            return await dispatcher_admin_client.resume_loop(loop_id_text)
        if command == "stop":
            return await dispatcher_admin_client.stop_loop(loop_id_text)
        if command == "confirm":
            return await dispatcher_admin_client.confirm_loop(loop_id_text, force=force)
        if command == "start_next_round":
            return await dispatcher_admin_client.start_next_round(loop_id_text)
        if command == "retry_round":
            if not round_id:
                raise BadRequestAppException("retry_round 必须提供 round_id")
            return await dispatcher_admin_client.retry_round(
                str(round_id),
                reason=reason,
            )
        raise BadRequestAppException(f"不支持的 dispatcher 命令: {command}")
    except Exception as exc:
        logger.warning("dispatcher loop 命令失败 command={} loop_id={} error={}", command, loop_id, exc)
        raise InternalServerErrorAppException("dispatcher loop 命令失败") from exc


def to_prediction_read(row, *, task=None) -> PredictionRead:
    task_status = getattr(task, "status", None)
    return PredictionRead(
        id=row.id,
        project_id=row.project_id,
        plugin_id=str(row.plugin_id or ""),
        model_id=row.model_id,
        base_commit_id=row.base_commit_id,
        task_id=row.task_id,
        task_status=task_status,
        scope_type=str(row.scope_type or ""),
        scope_payload=dict(row.scope_payload or {}),
        status=str(row.status or ""),
        total_items=int(row.total_items or 0),
        params=dict(row.params or {}),
        last_error=row.last_error,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_prediction_task_read(row, *, task=None) -> PredictionTaskRead:
    return PredictionTaskRead(**to_prediction_read(row, task=task).model_dump())
