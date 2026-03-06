from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import OrderedDict
from typing import Any

# Executor spawns plugin workers via subprocess; disable gRPC fork handlers to avoid
# noisy "skipping fork() handlers" warnings under multi-threaded workloads.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import grpc
from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.core.config import settings
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.grpc_gen import runtime_control_pb2_grpc as pb_grpc
from saki_executor.steps.manager import StepManager
from saki_executor.steps.state import ExecutorState
from saki_executor.plugins.registry import PluginRegistry


class AgentClient:
    def __init__(self, plugin_registry: PluginRegistry, step_manager: StepManager):
        self.plugin_registry = plugin_registry
        self.step_manager = step_manager

        self._outbox: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[pb.RuntimeMessage | list[pb.RuntimeMessage]]] = {}
        self._pending_data_chunks: dict[str, list[pb.RuntimeMessage]] = {}

        self._running = False
        self._connected = False
        self._connect_enabled = True
        self._last_heartbeat_ts: int | None = None
        self._active_call: grpc.aio.StreamStreamCall | None = None

        self._handled_control_acks: OrderedDict[str, pb.RuntimeMessage] = OrderedDict()
        self._max_cached_control_acks = 2048

    async def send_message(self, message: pb.RuntimeMessage) -> None:
        if not isinstance(message, pb.RuntimeMessage):
            raise TypeError("send_message only accepts RuntimeMessage")
        await self._outbox.put(message)

    async def request_message(
        self,
        message: pb.RuntimeMessage,
        timeout_sec: int = 60,
    ) -> pb.RuntimeMessage | list[pb.RuntimeMessage]:
        if not isinstance(message, pb.RuntimeMessage):
            raise TypeError("request_message only accepts RuntimeMessage")

        request_id = runtime_codec.get_message_request_id(message)
        if not request_id:
            request_id = str(uuid.uuid4())
            runtime_codec.set_message_request_id(message, request_id)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[pb.RuntimeMessage | list[pb.RuntimeMessage]] = loop.create_future()
        self._pending[request_id] = future
        await self.send_message(message)

        try:
            result = await asyncio.wait_for(future, timeout=timeout_sec)
            if isinstance(result, list):
                if result:
                    first = result[0]
                    if first.WhichOneof("payload") == "error":
                        parsed = runtime_codec.parse_error(first.error)
                        raise RuntimeError(str(parsed.get("error") or parsed.get("message") or "runtime error"))
                return result
            payload_type = result.WhichOneof("payload")
            if payload_type == "error":
                parsed = runtime_codec.parse_error(result.error)
                raise RuntimeError(str(parsed.get("error") or parsed.get("message") or "runtime error"))
            return result
        finally:
            self._pending.pop(request_id, None)
            self._pending_data_chunks.pop(request_id, None)

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
        logger.info("已启用连接，executor 将自动尝试连接 dispatcher。")

    async def disconnect(self, *, force: bool = False) -> bool:
        if self.step_manager.busy and not force:
            logger.warning("当前任务运行中，默认拒绝断开。若确认中断，请使用 disconnect --force。")
            return False

        if self.step_manager.busy and force:
            if self.step_manager.current_task_id:
                logger.warning("收到强制断连请求，先尝试停止任务 task_id={}。", self.step_manager.current_task_id)
                await self.step_manager.stop_task(self.step_manager.current_task_id)
            wait_sec = max(0, int(settings.DISCONNECT_FORCE_WAIT_SEC))
            if wait_sec > 0:
                deadline = time.monotonic() + wait_sec
                while self.step_manager.busy and time.monotonic() < deadline:
                    await asyncio.sleep(0.2)
            if self.step_manager.busy:
                logger.warning("强制断连等待超时，仍有任务运行，继续断开连接。")
            else:
                logger.info("任务已停止，继续断开连接。")

        if not self._connect_enabled and not self._connected:
            logger.info("连接已是断开状态。")
            return True

        self._connect_enabled = False
        call = self._active_call
        if call is not None:
            call.cancel()
        self._fail_pending("connection disabled by command")
        self._drain_outbox()
        logger.info("已禁用连接，当前连接将断开。")
        return True

    def _resource_payload(self) -> dict[str, Any]:
        return self.step_manager.get_host_resource_payload()

    def _register_message(self) -> pb.RuntimeMessage:
        plugins = []
        for plugin in self.plugin_registry.all():
            plugins.append(
                {
                    "plugin_id": plugin.plugin_id,
                    "version": plugin.version,
                    "display_name": plugin.display_name,
                    "supported_task_types": plugin.supported_task_types,
                    "supported_strategies": plugin.supported_strategies,
                    "supported_accelerators": plugin.supported_accelerators,
                    "supports_auto_fallback": plugin.supports_auto_fallback,
                    "request_config_schema": plugin.request_config_schema,
                    "default_request_config": plugin.default_request_config,
                }
            )
        return runtime_codec.build_register_message(
            request_id=str(uuid.uuid4()),
            executor_id=settings.EXECUTOR_ID,
            version=settings.EXECUTOR_VERSION,
            plugins=plugins,
            resources=self._resource_payload(),
        )

    def _heartbeat_message(self) -> pb.RuntimeMessage:
        return runtime_codec.build_heartbeat_message(
            request_id=str(uuid.uuid4()),
            executor_id=settings.EXECUTOR_ID,
            busy=self.step_manager.busy,
            current_task_id=self.step_manager.current_task_id,
            resources=self._resource_payload(),
        )

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings.HEARTBEAT_INTERVAL_SEC)
            self._last_heartbeat_ts = int(time.time())
            await self.send_message(self._heartbeat_message())
            logger.debug("已发送心跳 current_task_id={}", self.step_manager.current_task_id)

    async def _request_iterator(self):
        while self._running:
            try:
                message = await asyncio.wait_for(self._outbox.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            yield message

    def _cache_control_ack(self, request_id: str, ack_message: pb.RuntimeMessage) -> None:
        if not request_id:
            return
        self._handled_control_acks[request_id] = ack_message
        self._handled_control_acks.move_to_end(request_id)
        while len(self._handled_control_acks) > self._max_cached_control_acks:
            self._handled_control_acks.popitem(last=False)

    def _take_cached_control_ack(self, request_id: str) -> pb.RuntimeMessage | None:
        if not request_id:
            return None
        cached = self._handled_control_acks.get(request_id)
        if cached is not None:
            self._handled_control_acks.move_to_end(request_id)
        return cached

    def _drain_outbox(self) -> None:
        while True:
            try:
                self._outbox.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _fail_pending(self, reason: str) -> None:
        pending = list(self._pending.values())
        for future in pending:
            if not future.done():
                future.set_exception(RuntimeError(reason))
        self._pending.clear()
        self._pending_data_chunks.clear()

    async def _handle_incoming(self, message: pb.RuntimeMessage) -> None:
        payload_type = message.WhichOneof("payload")

        if payload_type == "data_response":
            reply_to = str(message.data_response.reply_to or "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                response = message.data_response
                is_chunked = bool(response.payload_id) or int(response.chunk_count) > 0
                if is_chunked:
                    chunks = self._pending_data_chunks.setdefault(reply_to, [])
                    chunks.append(message)
                    if response.is_last_chunk:
                        final_chunks = self._pending_data_chunks.pop(reply_to, [])
                        future.set_result(final_chunks or [message])
                else:
                    future.set_result(message)
            logger.debug("收到响应 type=data_response reply_to={}", reply_to)
            return

        if payload_type == "upload_ticket_response":
            reply_to = str(message.upload_ticket_response.reply_to or "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                future.set_result(message)
            logger.debug("收到响应 type=upload_ticket_response reply_to={}", reply_to)
            return

        if payload_type == "error":
            parsed = runtime_codec.parse_error(message.error)
            logger.error(
                "收到服务端错误消息: code={} message={} reason={} reply_to={} ack_for={}",
                parsed.get("code"),
                parsed.get("message"),
                parsed.get("reason"),
                parsed.get("reply_to"),
                parsed.get("ack_for"),
            )
            reply_to = str(parsed.get("reply_to") or parsed.get("ack_for") or parsed.get("request_id") or "")
            if reply_to:
                future = self._pending.get(reply_to)
                if future and not future.done():
                    future.set_result(message)
            return

        if payload_type == "ack":
            ack = message.ack
            if (
                int(ack.status) == pb.OK
                and int(ack.type) == pb.ACK_TYPE_REGISTER
                and int(ack.reason) == pb.ACK_REASON_REGISTERED
                and not self.step_manager.busy
            ):
                self.step_manager.executor_state = ExecutorState.IDLE
                self._connected = True
                logger.info(
                    "已与 dispatcher 建立连接并注册成功 executor_id={} target={}",
                    settings.EXECUTOR_ID,
                    settings.API_GRPC_TARGET,
                )
            return

        if payload_type == "assign_task":
            assign = message.assign_task
            request_id = str(assign.request_id or "")
            cached_ack = self._take_cached_control_ack(request_id)
            if cached_ack is not None:
                await self.send_message(cached_ack)
                logger.info("重复任务派发 request_id={}，已返回缓存 ack。", request_id)
                return

            task_payload = runtime_codec.parse_assign_task(assign)
            logger.info("收到任务派发 request_id={} task_id={}", request_id, task_payload.get("task_id"))
            ack_reason = "executor_busy"
            ack_detail = "executor busy"
            accepted = False
            try:
                accepted = await self.step_manager.assign_task(request_id, task_payload)
                if accepted:
                    ack_reason = "accepted"
                    ack_detail = "accepted"
            except Exception as exc:
                logger.warning("任务派发参数非法 request_id={} error={}", request_id, exc)
                ack_reason = "rejected"
                ack_detail = str(exc) or "rejected"
            ack_message = runtime_codec.build_ack_message(
                request_id=str(uuid.uuid4()),
                ack_for=request_id,
                ok=accepted,
                ack_type="assign_task",
                ack_reason=ack_reason,
                detail=ack_detail,
            )
            await self.send_message(ack_message)
            self._cache_control_ack(request_id, ack_message)
            return

        if payload_type == "stop_task":
            stop = message.stop_task
            request_id = str(stop.request_id or "")
            cached_ack = self._take_cached_control_ack(request_id)
            if cached_ack is not None:
                await self.send_message(cached_ack)
                logger.info("重复停止请求 request_id={}，已返回缓存 ack。", request_id)
                return

            task_id = str(stop.task_id or "")
            logger.info("收到任务停止请求 request_id={} task_id={}", request_id, task_id)
            stopped = await self.step_manager.stop_task(task_id)
            ack_message = runtime_codec.build_ack_message(
                request_id=str(uuid.uuid4()),
                ack_for=request_id,
                ok=stopped,
                ack_type="stop_task",
                ack_reason="stopping" if stopped else "task_not_running",
                detail="stopping" if stopped else "task not running",
            )
            await self.send_message(ack_message)
            self._cache_control_ack(request_id, ack_message)
            return

        logger.warning("收到未知消息类型: {}", payload_type)

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
                self.step_manager.executor_state = ExecutorState.OFFLINE
                await asyncio.sleep(0.2)
            if stop_event.is_set():
                break

            self._drain_outbox()
            self._handled_control_acks.clear()
            self.step_manager.executor_state = ExecutorState.CONNECTING
            self._running = True
            disconnect_reason = "stream closed by dispatcher"
            heartbeat_task = None
            try:
                logger.info(
                    "开始连接 dispatcher gRPC target={} executor_id={}",
                    settings.API_GRPC_TARGET,
                    settings.EXECUTOR_ID,
                )
                async with grpc.aio.insecure_channel(settings.API_GRPC_TARGET) as channel:
                    stub = pb_grpc.RuntimeControlStub(channel)
                    metadata = [("x-internal-token", settings.INTERNAL_TOKEN)]
                    call = stub.Stream(self._request_iterator(), metadata=metadata)
                    self._active_call = call

                    await self.send_message(self._register_message())
                    logger.info("已发送注册消息 executor_id={}", settings.EXECUTOR_ID)
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    async for runtime_message in call:
                        if stop_event.is_set():
                            disconnect_reason = "shutdown requested"
                            break
                        if not self._connect_enabled:
                            disconnect_reason = "connection disabled"
                            break
                        await self._handle_incoming(runtime_message)

                backoff = 1
            except grpc.aio.AioRpcError as exc:
                self.step_manager.executor_state = ExecutorState.ERROR_RECOVERY
                reason = self._format_rpc_error(exc)
                disconnect_reason = reason
                if not self._connect_enabled or stop_event.is_set():
                    logger.info("连接已断开：{}", reason)
                else:
                    logger.error("连接失败：{}", reason)
                    logger.info("本次连接失败，将在 {} 秒后重试。", backoff)
                await self._sleep_with_interrupt(backoff, stop_event)
                backoff = min(backoff * 2, 30)
            except Exception as exc:
                self.step_manager.executor_state = ExecutorState.ERROR_RECOVERY
                reason = str(exc) or exc.__class__.__name__
                disconnect_reason = reason
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
                self._fail_pending("grpc session ended")
                self._drain_outbox()
                if not self.step_manager.busy:
                    self.step_manager.executor_state = ExecutorState.OFFLINE
                logger.info(
                    "已断开与 dispatcher 的 gRPC 连接 target={} reason={} executor_state={} connect_enabled={}",
                    settings.API_GRPC_TARGET,
                    disconnect_reason,
                    self.step_manager.executor_state.value,
                    self._connect_enabled,
                )
