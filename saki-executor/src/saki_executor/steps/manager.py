from __future__ import annotations

import asyncio
from contextlib import suppress
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.core.config import settings
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.runtime.capability.host_capability_cache import HostCapabilityCache
from saki_executor.steps.contracts import (
    ArtifactDownloadTicket,
    ArtifactUploadTicket,
    FetchedPage,
    TaskExecutionRequest,
)
from saki_executor.steps.orchestration.error_codes import TaskErrorCode, TaskPipelineError, TaskStage
from saki_executor.steps.orchestration.runner import TaskPipelineRunner
from saki_executor.steps.services import ArtifactUploader, DataGateway, SamplingService
from saki_executor.steps.state import ExecutorState, TaskStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.plugins.registry import PluginRegistry
from saki_plugin_sdk import ExecutionBindingContext, ExecutorPlugin, HostCapabilitySnapshot, TaskReporter, WorkspaceProtocol

SendFn = Callable[[pb.RuntimeMessage], Awaitable[None]]
RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage | list[pb.RuntimeMessage]]]
HttpClientFactory = Callable[..., Any]
TransportStateGetter = Callable[[], bool]
FatalErrorCallback = Callable[[BaseException], None]


class TaskManager:
    def __init__(
        self,
        runs_dir: str,
        cache: AssetCache,
        plugin_registry: PluginRegistry,
        *,
        round_shared_cache_enabled: bool = True,
        strict_train_model_handoff: bool = True,
        send_message: SendFn | None = None,
        request_message: RequestFn | None = None,
        http_client_factory: HttpClientFactory | None = None,
        host_capability_cache: HostCapabilityCache | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.cache = cache
        self.plugin_registry = plugin_registry
        self.round_shared_cache_enabled = bool(round_shared_cache_enabled)
        self.strict_train_model_handoff = bool(strict_train_model_handoff)
        self._send_message = send_message
        self._request_message = request_message
        self._host_capability_cache = host_capability_cache or HostCapabilityCache(
            cpu_workers=settings.CPU_WORKERS,
            memory_mb=settings.MEMORY_MB,
        )

        self.executor_state = ExecutorState.IDLE
        self.current_task_id: str | None = None
        self.current_execution_id: str | None = None
        self.last_task_id: str | None = None
        self.last_execution_id: str | None = None
        self.last_task_status: TaskStatus | None = None
        self._active_plugin: ExecutorPlugin | None = None
        self._task: asyncio.Task | None = None
        self._current_request: TaskExecutionRequest | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stall_watchdog_task: asyncio.Task | None = None
        self._last_local_activity_at = time.monotonic()
        self._transport_state_getter: TransportStateGetter | None = None
        self._fatal_error_callback: FatalErrorCallback | None = None
        self._forced_terminal_status: TaskStatus | None = None
        self._forced_terminal_message = ""
        self._forced_terminal_report = True
        self._data_gateway = DataGateway(
            request_message_getter=lambda: self._request_message,
            execution_id_getter=lambda: self.current_execution_id,
            activity_callback=self.mark_local_activity,
        )
        self._sampling_service = SamplingService(
            fetch_page=self._fetch_page,
            cache=self.cache,
            stop_event=self._stop_event,
        )
        self._artifact_uploader = ArtifactUploader(
            client_factory=http_client_factory,
            activity_callback=self.mark_local_activity,
        )
        self.cache.set_activity_callback(self.mark_local_activity)

    def set_transport(self, send_message: SendFn, request_message: RequestFn) -> None:
        self._send_message = send_message
        self._request_message = request_message

    def set_transport_state_getter(self, getter: TransportStateGetter) -> None:
        self._transport_state_getter = getter

    def set_fatal_error_callback(self, callback: FatalErrorCallback | None) -> None:
        self._fatal_error_callback = callback

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "executor_state": self.executor_state.value,
            "busy": self.busy,
            "current_task_id": self.current_task_id,
            "current_execution_id": self.current_execution_id,
            "last_task_id": self.last_task_id,
            "last_execution_id": self.last_execution_id,
            "last_task_status": self.last_task_status.value if self.last_task_status else None,
            "host_capability_last_probe_ts": self._host_capability_cache.last_probe_ts if self._host_capability_cache else None,
            "last_local_activity_age_sec": round(max(0.0, time.monotonic() - self._last_local_activity_at), 3),
        }

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    def set_active_plugin(self, plugin: ExecutorPlugin | None) -> None:
        self._active_plugin = plugin

    def mark_local_activity(self, source: str = "") -> None:
        del source
        self._last_local_activity_at = time.monotonic()

    async def wait_until_idle(self, timeout_sec: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        while self.busy and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        return not self.busy

    async def abort_current_task(
        self,
        *,
        reason_code: str,
        reason_message: str,
        report_result: bool,
    ) -> bool:
        task_id = str(self.current_task_id or "").strip()
        execution_id = str(self.current_execution_id or "").strip()
        if not task_id:
            return not self.busy
        return await self._request_stop(
            task_id=task_id,
            execution_id=execution_id,
            final_status=TaskStatus.FAILED,
            terminal_message=f"[{reason_code}] {reason_message}",
            report_result=report_result,
        )

    def report_fatal_error(self, exc: BaseException) -> None:
        logger.critical("执行器检测到不可恢复错误 error={}", exc)
        if self._fatal_error_callback is not None:
            self._fatal_error_callback(exc)

    def get_host_capability_snapshot(self) -> HostCapabilitySnapshot:
        if self._host_capability_cache is None:
            raise RuntimeError("host capability cache is not configured")
        return self._host_capability_cache.get_snapshot()

    def refresh_host_capability(self) -> HostCapabilitySnapshot:
        if self._host_capability_cache is None:
            raise RuntimeError("host capability cache is not configured")
        return self._host_capability_cache.refresh()

    def get_host_resource_payload(self) -> dict[str, Any]:
        if self._host_capability_cache is None:
            raise RuntimeError("host capability cache is not configured")
        return self._host_capability_cache.get_resource_payload()

    async def send_runtime_message(self, message: pb.RuntimeMessage) -> None:
        if self._send_message is None:
            raise RuntimeError("task manager send transport is not configured")
        await self._send_message(message)

    async def push_task_event(self, task_id: str, event: dict[str, Any]) -> None:
        await self._push_event(task_id, event)

    async def request_upload_ticket(
        self,
        *,
        task_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        return await self._request_upload_ticket(
            task_id=task_id,
            artifact_name=artifact_name,
            content_type=content_type,
        )

    async def request_download_ticket(
        self,
        *,
        task_id: str,
        source_task_id: str | None,
        model_id: str | None,
        artifact_name: str,
    ) -> ArtifactDownloadTicket:
        return await self._request_download_ticket(
            task_id=task_id,
            source_task_id=source_task_id,
            model_id=model_id,
            artifact_name=artifact_name,
        )

    async def upload_artifact_with_retry(
        self,
        *,
        artifact_path: Path,
        upload_url: str,
        headers: dict[str, str],
    ) -> None:
        await self._upload_artifact_with_retry(
            artifact_path=artifact_path,
            upload_url=upload_url,
            headers=headers,
        )

    async def fetch_all_data(
        self,
        task_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        return await self._fetch_all(
            task_id=task_id,
            query_type=query_type,
            project_id=project_id,
            commit_id=commit_id,
            limit=limit,
        )

    async def collect_topk_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        strategy: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        topk: int,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        return await self._collect_topk_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=task_id,
            project_id=project_id,
            commit_id=commit_id,
            strategy=strategy,
            params=params,
            protected=protected,
            query_type=query_type,
            topk=topk,
            context=context,
        )

    async def collect_prediction_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        context: ExecutionBindingContext,
        emit_log=None,
    ) -> list[dict[str, Any]]:
        return await self._collect_prediction_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=task_id,
            project_id=project_id,
            commit_id=commit_id,
            params=params,
            protected=protected,
            query_type=query_type,
            context=context,
            emit_log=emit_log,
        )

    async def assign_task(self, request_id: str, payload: dict[str, Any]) -> bool:
        request = TaskExecutionRequest.from_payload(payload)
        async with self._lock:
            if self.busy:
                logger.warning(
                    "assign_trace 拒绝任务分配：执行器忙碌 request_id={} incoming_task_id={} incoming_execution_id={} current_task_id={} current_execution_id={}",
                    request_id,
                    request.task_id,
                    request.execution_id,
                    self.current_task_id,
                    self.current_execution_id,
                )
                return False
            self.current_task_id = request.task_id
            self.current_execution_id = request.execution_id
            self.executor_state = ExecutorState.RESERVED
            self._current_request = request
            self._stop_event.clear()
            self._forced_terminal_status = None
            self._forced_terminal_message = ""
            self._forced_terminal_report = True
            self.mark_local_activity("assign_task")
            self._task = asyncio.create_task(self._run_task(request))
            self._stall_watchdog_task = asyncio.create_task(
                self._stall_watchdog_loop(request),
                name=f"task-stall-watchdog-{request.task_id}",
            )
            logger.info(
                "assign_trace 接受任务分配 request_id={} task_id={} execution_id={} plugin_id={} task_type={} mode={} round_id={} attempt={}",
                request_id,
                self.current_task_id,
                self.current_execution_id,
                request.plugin_id,
                request.task_type,
                request.mode,
                request.round_id,
                request.attempt,
            )
            return True

    async def stop_task(self, task_id: str, execution_id: str | None = None) -> bool:
        return await self._request_stop(
            task_id=task_id,
            execution_id=str(execution_id or ""),
            final_status=TaskStatus.CANCELLED,
            terminal_message="已按请求取消",
            report_result=self._is_transport_available(),
        )

    async def _request_stop(
        self,
        *,
        task_id: str,
        execution_id: str,
        final_status: TaskStatus,
        terminal_message: str,
        report_result: bool,
    ) -> bool:
        execution_id = str(execution_id or "").strip()
        async with self._lock:
            current_execution_id = str(self.current_execution_id or "")
            if not self.busy or self.current_task_id != task_id:
                if self.last_task_id == task_id and self.last_task_status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.SKIPPED,
                } and (not execution_id or self.last_execution_id == execution_id):
                    return True
                return False
            if execution_id and current_execution_id and current_execution_id != execution_id:
                return False
            self._stop_event.set()
            plugin = self._active_plugin
            task = self._task
            self._forced_terminal_status = final_status
            self._forced_terminal_message = terminal_message
            self._forced_terminal_report = report_result
            logger.info("收到停止任务请求 task_id={} execution_id={}", task_id, current_execution_id)
        if plugin:
            try:
                await plugin.stop(task_id)
            except Exception:
                logger.exception("插件停止失败 task_id={} execution_id={}", task_id, current_execution_id)
        if task is None:
            return True
        if await self._wait_for_task_completion(task, settings.EXECUTOR_STOP_GRACE_SEC):
            return True
        logger.warning(
            "任务停止宽限期已超时，准备取消执行协程 task_id={} execution_id={}",
            task_id,
            current_execution_id,
        )
        task.cancel("executor stop timeout")
        if await self._wait_for_task_completion(task, settings.EXECUTOR_STOP_CANCEL_SEC):
            return True
        logger.error(
            "任务在取消后仍未结束 task_id={} execution_id={}",
            task_id,
            current_execution_id,
        )
        return False

    async def _run_task(self, request: TaskExecutionRequest) -> None:
        if self._send_message is None or self._request_message is None:
            raise RuntimeError("任务管理器传输通道未配置")
        final_status = TaskStatus.FAILED
        strategy = ""
        if request.task_type in {"score", "custom"}:
            sampling_cfg = request.resolved_params.get("sampling")
            if isinstance(sampling_cfg, dict):
                strategy = str(sampling_cfg.get("strategy") or "").strip()
            if not strategy:
                strategy = str(request.query_strategy or "").strip()
        inference_mode = "direct" if request.task_type == "predict" else ""
        logger.info(
            "assign_trace 任务开始执行 task_id={} execution_id={} round_id={} attempt={} plugin_id={} task_type={} mode={} sampling_strategy={} inference_mode={}",
            request.task_id,
            request.execution_id,
            request.round_id,
            request.attempt,
            request.plugin_id,
            request.task_type,
            request.mode,
            strategy,
            inference_mode,
        )
        try:
            result = await TaskPipelineRunner(manager=self, request=request).run()
            final_status = result.status
        except asyncio.CancelledError:
            final_status = await self._publish_forced_terminal_result(request)
        except Exception as exc:
            if self._stop_event.is_set() and self._forced_terminal_status is not None:
                final_status = await self._publish_forced_terminal_result(request)
            elif self._stop_event.is_set():
                final_status = await self._publish_cancelled_result(request)
            else:
                final_status = await self._publish_failed_result(request, exc)
        finally:
            await self._stop_stall_watchdog()
            await self._reset_after_task(request.task_id, request.execution_id, final_status)

    def _ensure_reporter(self, request: TaskExecutionRequest) -> TaskReporter:
        workspace = Workspace(
            self.runs_dir,
            request.task_id,
            round_id=request.round_id,
            attempt=request.attempt,
            prepared_data_cache_root=self.cache.root / "prepared_data_v2",
        )
        workspace.ensure()
        if not workspace.config_path.exists():
            workspace.write_config(request.raw_payload)
        return TaskReporter(request.task_id, workspace.events_path)

    async def _publish_cancelled_result(self, request: TaskExecutionRequest) -> TaskStatus:
        if self._send_message is None:
            raise RuntimeError("任务管理器发送通道未配置")
        self.executor_state = ExecutorState.FINALIZING
        self.mark_local_activity("task_result.cancelled")
        reporter = self._ensure_reporter(request)
        reporter.status(TaskStatus.CANCELLED.value, "任务已取消")
        for message in runtime_codec.build_task_result_message(
            request_id=str(uuid.uuid4()),
            task_id=request.task_id,
            execution_id=request.execution_id,
            status=TaskStatus.CANCELLED.value,
            metrics={},
            artifacts={},
            candidates=[],
            error_message="已按请求取消",
        ):
            await self._send_message(message)
        logger.warning("任务被取消 task_id={}", request.task_id)
        return TaskStatus.CANCELLED

    async def _publish_forced_terminal_result(self, request: TaskExecutionRequest) -> TaskStatus:
        status = self._forced_terminal_status or TaskStatus.CANCELLED
        message = self._forced_terminal_message or (
            "任务已取消" if status == TaskStatus.CANCELLED else "任务执行失败"
        )
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        reporter.status(status.value, message)
        if self._send_message is not None and self._forced_terminal_report:
            self.mark_local_activity("task_result.forced")
            for result_message in runtime_codec.build_task_result_message(
                request_id=str(uuid.uuid4()),
                task_id=request.task_id,
                execution_id=request.execution_id,
                status=status.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message=message if status == TaskStatus.FAILED else "",
            ):
                await self._send_message(result_message)
        if status == TaskStatus.FAILED:
            logger.error("任务被强制失败 task_id={} error={}", request.task_id, message)
        else:
            logger.warning("任务被强制取消 task_id={} reason={}", request.task_id, message)
        return status

    async def _publish_failed_result(self, request: TaskExecutionRequest, exc: Exception) -> TaskStatus:
        if self._send_message is None:
            raise RuntimeError("任务管理器发送通道未配置")
        self.executor_state = ExecutorState.FINALIZING
        if isinstance(exc, TaskPipelineError):
            error_message = exc.to_user_message()
        else:
            error_message = (
                f"[{TaskErrorCode.INTERNAL_ERROR.value}] {str(exc)} "
                f"(stage={TaskStage.EXECUTE.value})"
            )
        self.mark_local_activity("task_result.failed")
        reporter = self._ensure_reporter(request)
        reporter.status(TaskStatus.FAILED.value, error_message)
        for result_message in runtime_codec.build_task_result_message(
            request_id=str(uuid.uuid4()),
            task_id=request.task_id,
            execution_id=request.execution_id,
            status=TaskStatus.FAILED.value,
            metrics={},
            artifacts={},
            candidates=[],
            error_message=error_message,
        ):
            await self._send_message(result_message)
        logger.exception("任务执行失败 task_id={} error={}", request.task_id, error_message)
        return TaskStatus.FAILED

    async def _reset_after_task(self, task_id: str, execution_id: str, final_status: TaskStatus) -> None:
        async with self._lock:
            self.executor_state = ExecutorState.IDLE
            self.last_task_id = task_id
            self.last_execution_id = execution_id
            self.last_task_status = final_status
            self.current_task_id = None
            self.current_execution_id = None
            self._task = None
            self._current_request = None
            self._stop_event.clear()
            self._active_plugin = None
            self._forced_terminal_status = None
            self._forced_terminal_message = ""
            self._forced_terminal_report = True
            self._last_local_activity_at = time.monotonic()
        logger.info(
            "assign_trace 任务收尾完成 task_id={} execution_id={} final_status={}",
            task_id,
            execution_id,
            final_status.value,
        )

    async def _request_upload_ticket(
        self,
        *,
        task_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        return await self._data_gateway.request_upload_ticket(
            task_id=task_id,
            artifact_name=artifact_name,
            content_type=content_type,
        )

    async def _request_download_ticket(
        self,
        *,
        task_id: str,
        source_task_id: str | None,
        model_id: str | None,
        artifact_name: str,
    ) -> ArtifactDownloadTicket:
        return await self._data_gateway.request_download_ticket(
            task_id=task_id,
            source_task_id=source_task_id,
            model_id=model_id,
            artifact_name=artifact_name,
        )

    async def _upload_artifact_with_retry(
        self,
        *,
        artifact_path: Path,
        upload_url: str,
        headers: dict[str, str],
    ) -> None:
        await self._artifact_uploader.upload_with_retry(
            artifact_path=artifact_path,
            upload_url=upload_url,
            headers=headers,
        )

    async def _push_event(self, task_id: str, event: dict[str, Any]) -> None:
        if self._send_message is None:
            raise RuntimeError("任务管理器发送通道未配置")
        self.mark_local_activity(f"task_event:{str(event.get('event_type') or '')}")
        await self._send_message(
            runtime_codec.build_task_event_message(
                request_id=str(uuid.uuid4()),
                task_id=task_id,
                execution_id=self.current_execution_id,
                seq=int(event["seq"]),
                ts=int(event["ts"]),
                event_type=str(event["event_type"]),
                payload=event["payload"] or {},
            )
        )

    async def _fetch_all(
        self,
        task_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        return await self._data_gateway.fetch_all(
            task_id=task_id,
            query_type=query_type,
            project_id=project_id,
            commit_id=commit_id,
            limit=limit,
            stop_event=self._stop_event,
        )

    async def _fetch_page(
        self,
        *,
        task_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        cursor: str | None,
        limit: int,
    ) -> FetchedPage:
        return await self._data_gateway.fetch_page(
            task_id=task_id,
            query_type=query_type,
            project_id=project_id,
            commit_id=commit_id,
            cursor=cursor,
            limit=limit,
        )

    async def _collect_topk_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        strategy: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        topk: int,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        return await self._sampling_service.collect_topk_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=task_id,
            project_id=project_id,
            commit_id=commit_id,
            strategy=strategy,
            params=params,
            protected=protected,
            query_type=query_type,
            topk=topk,
            context=context,
        )

    async def _collect_prediction_candidates_streaming(
        self,
        *,
        plugin: ExecutorPlugin,
        workspace: WorkspaceProtocol,
        task_id: str,
        project_id: str,
        commit_id: str,
        params: dict[str, Any],
        protected: set[str],
        query_type: str,
        context: ExecutionBindingContext,
        emit_log=None,
    ) -> list[dict[str, Any]]:
        return await self._sampling_service.collect_prediction_candidates_streaming(
            plugin=plugin,
            workspace=workspace,
            task_id=task_id,
            project_id=project_id,
            commit_id=commit_id,
            params=params,
            protected=protected,
            query_type=query_type,
            context=context,
            emit_log=emit_log,
        )

    async def _stall_watchdog_loop(self, request: TaskExecutionRequest) -> None:
        timeout_sec = self._stall_timeout_for_task(request.task_type)
        if timeout_sec <= 0:
            return
        check_interval = min(5.0, max(1.0, timeout_sec / 12.0))
        try:
            while True:
                await asyncio.sleep(check_interval)
                if not self.busy:
                    return
                if self.current_task_id != request.task_id or self.current_execution_id != request.execution_id:
                    return
                if self._stop_event.is_set():
                    return
                idle_sec = time.monotonic() - self._last_local_activity_at
                if idle_sec < timeout_sec:
                    continue
                logger.error(
                    "检测到任务长时间无本地活动，准备强制回收 task_id={} execution_id={} task_type={} idle_sec={:.1f}",
                    request.task_id,
                    request.execution_id,
                    request.task_type,
                    idle_sec,
                )
                stopped = await self.abort_current_task(
                    reason_code="EXECUTION_STALLED",
                    reason_message=(
                        f"任务在 {idle_sec:.1f}s 内无本地活动 "
                        f"task_type={request.task_type}"
                    ),
                    report_result=self._is_transport_available(),
                )
                if not stopped:
                    self.report_fatal_error(
                        RuntimeError(
                            "任务长时间无本地活动且强制回收失败 "
                            f"task_id={request.task_id} execution_id={request.execution_id}"
                        )
                    )
                return
        except asyncio.CancelledError:
            return

    async def _stop_stall_watchdog(self) -> None:
        watchdog = self._stall_watchdog_task
        self._stall_watchdog_task = None
        if watchdog is None or watchdog.done() or watchdog is asyncio.current_task():
            return
        watchdog.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog

    async def _wait_for_task_completion(self, task: asyncio.Task, timeout_sec: float) -> bool:
        if task.done():
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.1, float(timeout_sec)))
            return True
        except asyncio.TimeoutError:
            return task.done()
        except asyncio.CancelledError:
            return task.done()
        except Exception:
            return task.done()

    def _stall_timeout_for_task(self, task_type: str) -> int:
        normalized = str(task_type or "").strip().lower()
        if normalized in {"train", "eval"}:
            return max(0, int(settings.TASK_STALL_TIMEOUT_TRAIN_SEC))
        if normalized in {"score", "predict", "custom"}:
            return max(0, int(settings.TASK_STALL_TIMEOUT_SCORE_SEC))
        return max(0, int(settings.TASK_STALL_TIMEOUT_PREPARE_SEC))

    def _is_transport_available(self) -> bool:
        if self._transport_state_getter is None:
            return self._send_message is not None
        try:
            return bool(self._transport_state_getter())
        except Exception:
            return False
