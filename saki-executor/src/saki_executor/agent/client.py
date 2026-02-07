from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import grpc

from saki_executor.core.config import settings
from saki_executor.jobs.manager import JobManager
from saki_executor.jobs.state import ExecutorState
from saki_executor.plugins.registry import PluginRegistry

_METHOD_PATH = "/saki.runtime.v1.RuntimeControl/Stream"


class AgentClient:
    def __init__(self, plugin_registry: PluginRegistry, job_manager: JobManager):
        self.plugin_registry = plugin_registry
        self.job_manager = job_manager
        self._outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future] = {}
        self._running = False

    async def send_message(self, message: dict[str, Any]) -> None:
        await self._outbox.put(message)

    async def request_message(self, message: dict[str, Any], timeout_sec: int = 60) -> dict[str, Any]:
        request_id = str(message.get("request_id") or uuid.uuid4())
        message["request_id"] = request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        await self.send_message(message)
        try:
            result = await asyncio.wait_for(future, timeout=timeout_sec)
            if result.get("error"):
                raise RuntimeError(str(result.get("error")))
            return result
        finally:
            self._pending.pop(request_id, None)

    def _resource_payload(self) -> dict[str, Any]:
        gpu_ids = [int(item.strip()) for item in settings.DEFAULT_GPU_IDS.split(",") if item.strip()]
        return {
            "gpu_count": len(gpu_ids),
            "gpu_device_ids": gpu_ids,
            "cpu_workers": settings.CPU_WORKERS or (os.cpu_count() or 1),
            "memory_mb": settings.MEMORY_MB,
        }

    def _register_payload(self) -> dict[str, Any]:
        plugins = []
        for plugin in self.plugin_registry.all():
            plugins.append(
                {
                    "plugin_id": plugin.plugin_id,
                    "version": plugin.version,
                    "supported_job_types": plugin.supported_job_types,
                    "supported_strategies": plugin.supported_strategies,
                }
            )
        return {
            "type": "register",
            "request_id": str(uuid.uuid4()),
            "executor_id": settings.EXECUTOR_ID,
            "version": settings.EXECUTOR_VERSION,
            "plugins": plugins,
            "resources": self._resource_payload(),
        }

    def _heartbeat_payload(self) -> dict[str, Any]:
        return {
            "type": "heartbeat",
            "request_id": str(uuid.uuid4()),
            "executor_id": settings.EXECUTOR_ID,
            "busy": self.job_manager.busy,
            "current_job_id": self.job_manager.current_job_id,
            "resources": self._resource_payload(),
        }

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings.HEARTBEAT_INTERVAL_SEC)
            await self.send_message(self._heartbeat_payload())

    async def _request_iterator(self):
        while self._running:
            message = await self._outbox.get()
            yield json.dumps(message, ensure_ascii=False).encode("utf-8")

    async def _handle_incoming(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type in {"data_response", "upload_ticket_response"}:
            reply_to = str(message.get("reply_to") or "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                future.set_result(message)
            return

        if msg_type == "error":
            reply_to = str(message.get("reply_to") or message.get("ack_for") or "")
            if reply_to:
                future = self._pending.get(reply_to)
                if future and not future.done():
                    future.set_result(message)
            return

        if msg_type == "ack":
            if str(message.get("message") or "") == "registered" and not self.job_manager.busy:
                self.job_manager.executor_state = ExecutorState.IDLE
            return

        if msg_type == "assign_job":
            accepted = await self.job_manager.assign_job(str(message.get("request_id") or ""), message.get("job") or {})
            await self.send_message(
                {
                    "type": "ack",
                    "request_id": str(uuid.uuid4()),
                    "ack_for": message.get("request_id"),
                    "status": "ok" if accepted else "error",
                    "message": "accepted" if accepted else "executor busy",
                }
            )
            return

        if msg_type == "stop_job":
            stopped = await self.job_manager.stop_job(str(message.get("job_id") or ""))
            await self.send_message(
                {
                    "type": "ack",
                    "request_id": str(uuid.uuid4()),
                    "ack_for": message.get("request_id"),
                    "status": "ok" if stopped else "error",
                    "message": "stopping" if stopped else "job not running",
                }
            )
            return

    async def run(self) -> None:
        backoff = 1
        while True:
            self.job_manager.executor_state = ExecutorState.CONNECTING
            self._running = True
            heartbeat_task = None
            try:
                async with grpc.aio.insecure_channel(settings.API_GRPC_TARGET) as channel:
                    rpc = channel.stream_stream(
                        _METHOD_PATH,
                        request_serializer=lambda x: x,
                        response_deserializer=lambda x: x,
                    )
                    metadata = [("x-internal-token", settings.INTERNAL_TOKEN)]
                    call = rpc(self._request_iterator(), metadata=metadata)

                    await self.send_message(self._register_payload())
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    async for raw in call:
                        message = json.loads(raw.decode("utf-8"))
                        await self._handle_incoming(message)

                backoff = 1
            except Exception:
                self.job_manager.executor_state = ExecutorState.ERROR_RECOVERY
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                self._running = False
                if heartbeat_task:
                    heartbeat_task.cancel()
                if not self.job_manager.busy:
                    self.job_manager.executor_state = ExecutorState.OFFLINE
