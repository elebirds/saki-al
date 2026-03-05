"""Loop action command endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import DispatcherAdminClientDep, RuntimeServiceDep
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.runtime.api.http.support.loop_control_helpers import (
    dispatch_loop_command,
    ensure_loop_project_perm,
)
from saki_api.modules.runtime.api.round_step import (
    LoopActionRequest,
    LoopActionResponse,
    LoopActionSpec,
)
from saki_api.modules.shared.modeling.enums import LoopActionKey

router = APIRouter()


@router.post("/loops/{loop_id}:act", response_model=LoopActionResponse)
async def act_loop(
    *,
    loop_id: uuid.UUID,
    payload: LoopActionRequest,
    runtime_service: RuntimeServiceDep,
    dispatcher_admin_client: DispatcherAdminClientDep,
    session: AsyncSession = Depends(get_session),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    await ensure_loop_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=loop.project_id,
        required=Permissions.LOOP_MANAGE,
    )

    _decision, action_key, matched = await runtime_service.resolve_loop_action_request(
        loop_id=loop_id,
        requested_action=(payload.action.value if payload.action else None),
        decision_token=payload.decision_token,
    )
    action_payload = {}
    if isinstance(matched.get("payload"), dict):
        action_payload.update(matched["payload"])
    if payload.payload:
        action_payload.update(payload.payload)

    executed_action: LoopActionKey | None = None
    command_id: str | None = None
    message_text = f"{action_key} executed"

    if action_key == LoopActionKey.SNAPSHOT_INIT.value:
        result = await runtime_service.init_loop_snapshot(
            loop_id=loop_id,
            payload=action_payload,
            actor_user_id=current_user_id,
        )
        executed_action = LoopActionKey.SNAPSHOT_INIT
        message_text = (
            f"snapshot initialized: v{int(result.get('version_index') or 0)} "
            f"sample_count={int(result.get('sample_count') or 0)}"
        )
    elif action_key == LoopActionKey.SNAPSHOT_UPDATE.value:
        result = await runtime_service.update_loop_snapshot(
            loop_id=loop_id,
            payload=action_payload,
            actor_user_id=current_user_id,
        )
        executed_action = LoopActionKey.SNAPSHOT_UPDATE
        message_text = (
            f"snapshot updated: v{int(result.get('version_index') or 0)} "
            f"sample_count={int(result.get('sample_count') or 0)}"
        )
    elif action_key == LoopActionKey.RETRY_ROUND.value:
        retry_round_raw = action_payload.get("round_id")
        retry_round_id = uuid.UUID(str(retry_round_raw)) if retry_round_raw else None
        if retry_round_id is None:
            raise BadRequestAppException("retry_round action missing round_id")
        response = await dispatch_loop_command(
            command="retry_round",
            loop_id=loop_id,
            round_id=retry_round_id,
            reason=str(action_payload.get("reason") or "act retry latest failed round"),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey.RETRY_ROUND
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or "retry_round dispatched")
    elif action_key == LoopActionKey.START.value:
        bootstrap_result = await runtime_service.ensure_simulation_snapshot_bootstrap(
            loop_id=loop_id,
            actor_user_id=current_user_id,
        )
        if bootstrap_result is not None:
            await session.commit()
        response = await dispatch_loop_command(
            command=action_key,
            loop_id=loop_id,
            force=bool(payload.force),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey(action_key)
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or f"{action_key} dispatched")
    elif action_key in {
        LoopActionKey.START_NEXT_ROUND.value,
        LoopActionKey.PAUSE.value,
        LoopActionKey.RESUME.value,
        LoopActionKey.STOP.value,
        LoopActionKey.CONFIRM.value,
    }:
        response = await dispatch_loop_command(
            command=action_key,
            loop_id=loop_id,
            force=bool(payload.force),
            dispatcher_admin_client=dispatcher_admin_client,
        )
        executed_action = LoopActionKey(action_key)
        command_id = str(getattr(response, "command_id", "") or getattr(response, "request_id", "") or "")
        message_text = str(getattr(response, "message", "") or f"{action_key} dispatched")
    else:
        raise BadRequestAppException(f"unsupported action: {action_key}")

    gate_payload = await runtime_service.get_loop_gate(loop_id=loop_id)
    loop = await runtime_service.loop_repo.get_by_id_or_raise(loop_id)
    return LoopActionResponse(
        loop_id=loop.id,
        executed_action=executed_action,
        command_id=command_id,
        message=message_text,
        gate=gate_payload["gate"],
        gate_meta=gate_payload.get("gate_meta") or {},
        primary_action=LoopActionSpec.model_validate(gate_payload.get("primary_action"))
        if gate_payload.get("primary_action")
        else None,
        actions=[LoopActionSpec.model_validate(item) for item in gate_payload.get("actions") or []],
        decision_token=str(gate_payload.get("decision_token") or ""),
        blocking_reasons=list(gate_payload.get("blocking_reasons") or []),
        phase=loop.phase,
        lifecycle=loop.lifecycle,
    )
