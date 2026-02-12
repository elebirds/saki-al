"""Ingress service for runtime register/heartbeat handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from saki_api.modules.runtime.service.application.control_plane_dto import RuntimeHeartbeatDTO, RuntimeRegisterDTO


@dataclass(slots=True)
class RuntimeConnectionResult:
    accepted: bool
    executor_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_reason: str | None = None


class RuntimeConnectionIngressService:
    """Handle register/heartbeat business semantics for runtime ingress."""

    def __init__(self, dispatcher: Any) -> None:
        self._dispatcher = dispatcher

    async def handle_register(self, payload: RuntimeRegisterDTO) -> RuntimeConnectionResult:
        executor_id = str(payload.executor_id or "").strip()
        if not executor_id:
            return RuntimeConnectionResult(
                accepted=False,
                error_code="invalid_register",
                error_message="executor_id is required",
                error_reason="executor_id_required",
            )

        await self._dispatcher.register_executor(
            executor_id=executor_id,
            version=payload.version,
            plugin_payloads=[asdict(item) for item in payload.plugins],
            resources=payload.resources or {},
        )
        return RuntimeConnectionResult(accepted=True, executor_id=executor_id)

    async def handle_heartbeat(
            self,
            payload: RuntimeHeartbeatDTO,
            *,
            stream_executor_id: str | None,
    ) -> RuntimeConnectionResult:
        executor_id = str(payload.executor_id or "").strip()
        if not executor_id:
            return RuntimeConnectionResult(
                accepted=False,
                error_code="invalid_heartbeat",
                error_message="executor_id is required",
                error_reason="executor_id_required",
            )

        if stream_executor_id and stream_executor_id != executor_id:
            return RuntimeConnectionResult(
                accepted=False,
                error_code="executor_id_conflict",
                error_message="heartbeat executor_id does not match stream register executor_id",
                error_reason="executor_id_conflict",
            )

        await self._dispatcher.handle_heartbeat(
            executor_id=executor_id,
            busy=bool(payload.busy),
            current_task_id=payload.current_task_id,
            resources=payload.resources or {},
        )
        return RuntimeConnectionResult(accepted=True, executor_id=executor_id)
