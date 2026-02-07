from __future__ import annotations

import asyncio
import os
from typing import Dict

from loguru import logger

from saki_runtime.agent.command_router import CommandRouter
from saki_runtime.agent.messages import (
    build_ack,
    build_error,
    build_event_message,
    build_heartbeat,
    build_register,
)
from saki_runtime.agent.stream_manager import GrpcStreamManager
from saki_runtime.core.config import settings
from saki_runtime.grpc_gen import runtime_agent_pb2 as pb2
from saki_runtime.schemas.events import EventEnvelope


class AgentClient:
    def __init__(self, router: CommandRouter):
        self.router = router
        self._running = False
        self._stream = GrpcStreamManager(
            settings.API_GRPC_TARGET,
            settings.INTERNAL_TOKEN,
            self._handle_message,
            on_connect=self._on_connect,
        )

    def _build_resources(self) -> pb2.Resources:
        cpu_workers = os.cpu_count() or 1
        return pb2.Resources(
            gpu_count=1,
            gpu_device_ids=[0],
            cpu_workers=cpu_workers,
            memory_mb=0,
        )

    async def publish(self, message: pb2.AgentMessage) -> None:
        await self._stream.send(message)

    async def publish_event(self, event: EventEnvelope) -> None:
        await self.publish(build_event_message(event))

    async def _heartbeat_loop(self) -> None:
        resources = self._build_resources()
        while self._running:
            await asyncio.sleep(settings.HEARTBEAT_INTERVAL_SEC)
            await self.publish(build_heartbeat(resources))

    async def _on_connect(self) -> None:
        resources = self._build_resources()
        await self.publish(build_register(self.router.job_manager.list_plugins(), resources))

    async def _handle_message(self, message: pb2.AgentMessage) -> None:
        if not message.HasField("command"):
            return
        command = message.command
        request_id = command.request_id
        await self.publish(build_ack(request_id, pb2.ACK_OK, "received"))
        try:
            result = await asyncio.wait_for(
                self.router.handle(command),
                timeout=settings.COMMAND_TIMEOUT_SEC,
            )
            if result:
                await self.publish(result)
        except Exception as e:
            logger.exception("Failed to handle command")
            await self.publish(build_error(request_id, e))

    async def run(self) -> None:
        self._running = True
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await self._stream.run_forever()
        finally:
            self._running = False
            heartbeat_task.cancel()
