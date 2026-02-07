from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any

import grpc
from loguru import logger

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
        self._connected = False
        self._connect_enabled = True
        self._last_heartbeat_ts: int | None = None
        self._active_call: grpc.aio.StreamStreamCall | None = None

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

    def transport_snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "connected": self._connected,
            "connect_enabled": self._connect_enabled,
            "pending_requests": len(self._pending),
            "outbox_size": self._outbox.qsize(),
            "last_heartbeat_ts": self._last_heartbeat_ts,
        }

    async def connect(self) -> None:
        if self._connect_enabled:
            logger.info("连接已是启用状态。")
            return
        self._connect_enabled = True
        logger.info("已启用连接，executor 将自动尝试连接 saki-api。")

    async def disconnect(self) -> None:
        if not self._connect_enabled and not self._connected:
            logger.info("连接已是断开状态。")
            return
        self._connect_enabled = False
        call = self._active_call
        if call is not None:
            call.cancel()
        logger.info("已禁用连接，当前连接将断开。")

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
            self._last_heartbeat_ts = int(time.time())
            await self.send_message(self._heartbeat_payload())
            logger.debug("已发送心跳 current_job_id={}", self.job_manager.current_job_id)

    async def _request_iterator(self):
        while self._running:
            try:
                message = await asyncio.wait_for(self._outbox.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            yield json.dumps(message, ensure_ascii=False).encode("utf-8")

    async def _handle_incoming(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type in {"data_response", "upload_ticket_response"}:
            reply_to = str(message.get("reply_to") or "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                future.set_result(message)
            logger.debug("收到响应 type={} reply_to={}", msg_type, reply_to)
            return

        if msg_type == "error":
            logger.error("收到服务端错误消息: {}", message)
            reply_to = str(message.get("reply_to") or message.get("ack_for") or "")
            if reply_to:
                future = self._pending.get(reply_to)
                if future and not future.done():
                    future.set_result(message)
            return

        if msg_type == "ack":
            if str(message.get("message") or "") == "registered" and not self.job_manager.busy:
                self.job_manager.executor_state = ExecutorState.IDLE
                self._connected = True
                logger.info("执行器注册成功 executor_id={}", settings.EXECUTOR_ID)
            return

        if msg_type == "assign_job":
            logger.info("收到任务派发 request_id={} job_id={}", message.get("request_id"), message.get("job", {}).get("job_id"))
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
            logger.info("收到任务停止请求 request_id={} job_id={}", message.get("request_id"), message.get("job_id"))
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

        logger.warning("收到未知消息类型: {}", msg_type)

    @staticmethod
    def _format_rpc_error(exc: grpc.aio.AioRpcError) -> str:
        code = exc.code().name if hasattr(exc, "code") and exc.code() else "UNKNOWN"
        details = exc.details() if hasattr(exc, "details") and exc.details() else str(exc)
        return f"{code}: {details}"

    async def _sleep_with_interrupt(self, seconds: int, stop_event: asyncio.Event) -> None:
        start = time.monotonic()
        while (time.monotonic() - start) < seconds:
            if stop_event.is_set() or not self._connect_enabled:
                return
            await asyncio.sleep(0.2)

    async def run(self, shutdown_event: asyncio.Event | None = None) -> None:
        stop_event = shutdown_event or asyncio.Event()
        backoff = 1
        while not stop_event.is_set():
            while not stop_event.is_set() and not self._connect_enabled:
                self.job_manager.executor_state = ExecutorState.OFFLINE
                await asyncio.sleep(0.2)
            if stop_event.is_set():
                break

            self.job_manager.executor_state = ExecutorState.CONNECTING
            self._running = True
            heartbeat_task = None
            try:
                logger.info(
                    "开始连接 saki-api gRPC target={} executor_id={}",
                    settings.API_GRPC_TARGET,
                    settings.EXECUTOR_ID,
                )
                async with grpc.aio.insecure_channel(settings.API_GRPC_TARGET) as channel:
                    rpc = channel.stream_stream(
                        _METHOD_PATH,
                        request_serializer=lambda x: x,
                        response_deserializer=lambda x: x,
                    )
                    metadata = [("x-internal-token", settings.INTERNAL_TOKEN)]
                    call = rpc(self._request_iterator(), metadata=metadata)
                    self._active_call = call

                    await self.send_message(self._register_payload())
                    logger.info("已发送注册消息 executor_id={}", settings.EXECUTOR_ID)
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    async for raw in call:
                        if stop_event.is_set() or not self._connect_enabled:
                            break
                        message = json.loads(raw.decode("utf-8"))
                        await self._handle_incoming(message)

                backoff = 1
            except grpc.aio.AioRpcError as exc:
                self.job_manager.executor_state = ExecutorState.ERROR_RECOVERY
                reason = self._format_rpc_error(exc)
                if not self._connect_enabled or stop_event.is_set():
                    logger.info("连接已断开：{}", reason)
                else:
                    logger.error("连接失败：{}", reason)
                    logger.info("本次连接失败，将在 {} 秒后重试。", backoff)
                await self._sleep_with_interrupt(backoff, stop_event)
                backoff = min(backoff * 2, 30)
            except Exception as exc:
                self.job_manager.executor_state = ExecutorState.ERROR_RECOVERY
                reason = str(exc) or exc.__class__.__name__
                if not self._connect_enabled or stop_event.is_set():
                    logger.info("连接已断开：{}", reason)
                else:
                    logger.error("连接失败：{}", reason)
                    logger.info("本次连接失败，将在 {} 秒后重试。", backoff)
                await self._sleep_with_interrupt(backoff, stop_event)
                backoff = min(backoff * 2, 30)
            finally:
                self._running = False
                self._connected = False
                self._active_call = None
                if heartbeat_task:
                    heartbeat_task.cancel()
                if not self.job_manager.busy:
                    self.job_manager.executor_state = ExecutorState.OFFLINE
                logger.info(
                    "gRPC 会话已结束，executor_state={} connect_enabled={}",
                    self.job_manager.executor_state.value,
                    self._connect_enabled,
                )
