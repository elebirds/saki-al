"""Runtime control gRPC server for Task-based runtime protocol."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Optional

import grpc
from loguru import logger

from saki_api.core.config import settings
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_control_pb2_grpc as pb_grpc
from saki_api.infra.db.session import SessionLocal
from saki_api.infra.grpc.dispatcher import runtime_dispatcher
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.runtime.service.ingress.connection_ingress_service import RuntimeConnectionIngressService
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.runtime.service.ingress.control_router_service import RuntimeControlRouterService


@dataclass
class _RuntimeStreamState:
    outbox: asyncio.Queue[pb.RuntimeMessage]
    executor_id: str | None = None
    closed: bool = False


class RuntimeControlService(pb_grpc.RuntimeControlServicer):
    def __init__(self) -> None:
        self._storage = None
        self._connection_ingress = RuntimeConnectionIngressService(dispatcher=runtime_dispatcher)
        self._ingress = RuntimeControlIngressService(
            session_local=SessionLocal,
            storage_resolver=self._resolve_storage,
        )
        self._router = RuntimeControlRouterService(
            dispatcher=runtime_dispatcher,
            connection_ingress=self._connection_ingress,
            ingress=self._ingress,
        )

    def _resolve_storage(self):
        return self.storage

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def Stream(self, request_iterator, context):  # noqa: N802
        state = _RuntimeStreamState(outbox=asyncio.Queue())
        consumer = asyncio.create_task(self._consume_incoming(request_iterator=request_iterator, state=state))

        try:
            while True:
                message = await self._next_outgoing(state=state)
                if message is not None:
                    yield message
                    continue

                if consumer.done():
                    break
        finally:
            state.closed = True
            consumer.cancel()
            with contextlib.suppress(Exception):
                await consumer
            await self._router.on_stream_closed(executor_id=state.executor_id)

    async def _consume_incoming(self, *, request_iterator, state: _RuntimeStreamState) -> None:
        try:
            async for message in request_iterator:
                response = await self._handle_message(message=message, state=state)
                if response is not None:
                    await state.outbox.put(response)
        except grpc.RpcError as exc:
            logger.warning("runtime stream closed by grpc error={}", exc)
        except Exception:
            logger.exception("runtime stream incoming consume failed")

    async def _next_outgoing(self, *, state: _RuntimeStreamState) -> Optional[pb.RuntimeMessage]:
        if not state.outbox.empty():
            return state.outbox.get_nowait()

        if state.executor_id:
            control_message = await self._router.pull_dispatch_message(executor_id=state.executor_id, timeout=0.2)
            if control_message is not None:
                return control_message

        try:
            return await asyncio.wait_for(state.outbox.get(), timeout=0.2)
        except asyncio.TimeoutError:
            return None

    async def _handle_message(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> Optional[pb.RuntimeMessage]:
        result = await self._router.route_message(
            message=message,
            current_executor_id=state.executor_id,
        )
        if result.update_executor_id:
            state.executor_id = result.next_executor_id
        return result.response


class RuntimeGrpcServer:
    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._service = RuntimeControlService()

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = grpc.aio.server()
        pb_grpc.add_RuntimeControlServicer_to_server(self._service, self._server)
        self._server.add_insecure_port(settings.RUNTIME_GRPC_BIND)
        await self._server.start()
        logger.info("runtime grpc server started bind={}", settings.RUNTIME_GRPC_BIND)

    async def stop(self) -> None:
        if self._server is None:
            return
        await self._server.stop(grace=2)
        await self._server.wait_for_termination()
        self._server = None
        logger.info("runtime grpc server stopped")


runtime_grpc_server = RuntimeGrpcServer()
