"""Router service for runtime-control ingress payload handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.infra.grpc import runtime_codec
from saki_api.modules.runtime.service.ingress.connection_ingress_service import RuntimeConnectionIngressService
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService


@dataclass(slots=True)
class RuntimeControlRouteResult:
    response: pb.RuntimeMessage | None = None
    next_executor_id: str | None = None
    update_executor_id: bool = False


class RuntimeControlRouterService:
    """Handle runtime-control message routing and response composition."""

    def __init__(
            self,
            *,
            dispatcher: Any,
            connection_ingress: RuntimeConnectionIngressService,
            ingress: RuntimeControlIngressService,
    ) -> None:
        self._dispatcher = dispatcher
        self._connection_ingress = connection_ingress
        self._ingress = ingress

    async def route_message(
            self,
            *,
            message: pb.RuntimeMessage,
            current_executor_id: str | None,
    ) -> RuntimeControlRouteResult:
        payload_type = message.WhichOneof("payload")

        if payload_type == "register":
            return await self._handle_register(message.register)

        if payload_type == "heartbeat":
            return await self._handle_heartbeat(message.heartbeat, current_executor_id=current_executor_id)

        if payload_type == "ack":
            await self._dispatcher.handle_ack(message.ack)
            return RuntimeControlRouteResult()

        if payload_type == "task_event":
            await self._ingress.persist_task_event(message.task_event)
            return RuntimeControlRouteResult(
                response=runtime_codec.build_ack_message(
                    ack_for=str(message.task_event.request_id),
                    status=pb.OK,
                    ack_type=pb.ACK_TYPE_REQUEST,
                    ack_reason=pb.ACK_REASON_ACCEPTED,
                    detail="task_event persisted",
                )
            )

        if payload_type == "task_result":
            await self._ingress.persist_task_result(message.task_result)
            return RuntimeControlRouteResult(
                response=runtime_codec.build_ack_message(
                    ack_for=str(message.task_result.request_id),
                    status=pb.OK,
                    ack_type=pb.ACK_TYPE_REQUEST,
                    ack_reason=pb.ACK_REASON_ACCEPTED,
                    detail="task_result persisted",
                )
            )

        if payload_type == "data_request":
            return RuntimeControlRouteResult(
                response=await self._ingress.handle_data_request(message.data_request)
            )

        if payload_type == "upload_ticket_request":
            return RuntimeControlRouteResult(
                response=await self._ingress.handle_upload_ticket_request(message.upload_ticket_request)
            )

        if payload_type == "error":
            logger.warning(
                "runtime error from executor request_id={} code={} message={} reason={}",
                message.error.request_id,
                message.error.code,
                message.error.message,
                message.error.reason,
            )
            return RuntimeControlRouteResult()

        return RuntimeControlRouteResult(
            response=runtime_codec.build_error_message(
                code="unknown_payload",
                message=f"unsupported payload type: {payload_type}",
                reason="unsupported_payload",
            )
        )

    async def pull_dispatch_message(
            self,
            *,
            executor_id: str,
            timeout: float = 0.2,
    ) -> pb.RuntimeMessage | None:
        return await self._dispatcher.get_outgoing(executor_id, timeout=timeout)

    async def on_stream_closed(self, *, executor_id: str | None) -> None:
        if not executor_id:
            return
        await self._dispatcher.unregister_executor(executor_id)

    async def _handle_register(self, message: pb.Register) -> RuntimeControlRouteResult:
        payload = runtime_codec.parse_register(message)
        result = await self._connection_ingress.handle_register(payload)
        if not result.accepted:
            return RuntimeControlRouteResult(
                response=runtime_codec.build_error_message(
                    code=str(result.error_code or "invalid_register"),
                    message=str(result.error_message or "executor_id is required"),
                    reply_to=str(message.request_id),
                    reason=str(result.error_reason or "executor_id_required"),
                )
            )

        return RuntimeControlRouteResult(
            response=runtime_codec.build_ack_message(
                ack_for=str(message.request_id),
                status=pb.OK,
                ack_type=pb.ACK_TYPE_REGISTER,
                ack_reason=pb.ACK_REASON_REGISTERED,
                detail="registered",
            ),
            next_executor_id=result.executor_id,
            update_executor_id=True,
        )

    async def _handle_heartbeat(
            self,
            message: pb.Heartbeat,
            *,
            current_executor_id: str | None,
    ) -> RuntimeControlRouteResult:
        payload = runtime_codec.parse_heartbeat(message)
        result = await self._connection_ingress.handle_heartbeat(
            payload,
            stream_executor_id=current_executor_id,
        )
        if not result.accepted:
            return RuntimeControlRouteResult(
                response=runtime_codec.build_error_message(
                    code=str(result.error_code or "invalid_heartbeat"),
                    message=str(result.error_message or "executor_id is required"),
                    reply_to=str(message.request_id),
                    reason=str(result.error_reason or "executor_id_required"),
                )
            )

        return RuntimeControlRouteResult(
            response=runtime_codec.build_ack_message(
                ack_for=str(message.request_id),
                status=pb.OK,
                ack_type=pb.ACK_TYPE_REQUEST,
                ack_reason=pb.ACK_REASON_ACCEPTED,
                detail="heartbeat accepted",
            ),
            next_executor_id=result.executor_id,
            update_executor_id=True,
        )
