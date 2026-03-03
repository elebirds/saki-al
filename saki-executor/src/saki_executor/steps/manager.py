from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.core.config import settings
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.runtime.capability.host_capability_cache import HostCapabilityCache
from saki_executor.steps.contracts import ArtifactUploadTicket, FetchedPage, StepExecutionRequest
from saki_executor.steps.orchestration.error_codes import StepErrorCode, StepPipelineError, StepStage
from saki_executor.steps.orchestration.runner import StepPipelineRunner
from saki_executor.steps.services import ArtifactUploader, DataGateway, SamplingService
from saki_executor.steps.state import ExecutorState, StepStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.plugins.registry import PluginRegistry
from saki_plugin_sdk import ExecutionBindingContext, ExecutorPlugin, HostCapabilitySnapshot, StepReporter, WorkspaceProtocol

SendFn = Callable[[pb.RuntimeMessage], Awaitable[None]]
RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage | list[pb.RuntimeMessage]]]
HttpClientFactory = Callable[..., Any]


class StepManager:
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
        self.current_step_id: str | None = None
        self.last_step_id: str | None = None
        self.last_step_status: StepStatus | None = None
        self._active_plugin: ExecutorPlugin | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._data_gateway = DataGateway(request_message_getter=lambda: self._request_message)
        self._sampling_service = SamplingService(
            fetch_page=self._fetch_page,
            cache=self.cache,
            stop_event=self._stop_event,
        )
        self._artifact_uploader = ArtifactUploader(client_factory=http_client_factory)

    def set_transport(self, send_message: SendFn, request_message: RequestFn) -> None:
        self._send_message = send_message
        self._request_message = request_message

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "executor_state": self.executor_state.value,
            "busy": self.busy,
            "current_step_id": self.current_step_id,
            "last_step_id": self.last_step_id,
            "last_step_status": self.last_step_status.value if self.last_step_status else None,
            "host_capability_last_probe_ts": self._host_capability_cache.last_probe_ts if self._host_capability_cache else None,
        }

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    def set_active_plugin(self, plugin: ExecutorPlugin | None) -> None:
        self._active_plugin = plugin

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
            raise RuntimeError("step manager send transport is not configured")
        await self._send_message(message)

    async def push_step_event(self, step_id: str, event: dict[str, Any]) -> None:
        await self._push_event(step_id, event)

    async def request_upload_ticket(
        self,
        *,
        step_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        return await self._request_upload_ticket(
            step_id=step_id,
            artifact_name=artifact_name,
            content_type=content_type,
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
        step_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        return await self._fetch_all(
            step_id=step_id,
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
        step_id: str,
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
            step_id=step_id,
            project_id=project_id,
            commit_id=commit_id,
            strategy=strategy,
            params=params,
            protected=protected,
            query_type=query_type,
            topk=topk,
            context=context,
        )

    async def assign_step(self, request_id: str, payload: dict[str, Any]) -> bool:
        request = StepExecutionRequest.from_payload(payload)
        async with self._lock:
            if self.busy:
                logger.warning("拒绝任务分配：executor 忙碌，request_id={}", request_id)
                return False
            self.current_step_id = request.step_id
            self.executor_state = ExecutorState.RESERVED
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_task(request))
            logger.info(
                "接受任务分配 request_id={} step_id={} plugin_id={}",
                request_id,
                self.current_step_id,
                request.plugin_id,
            )
            return True

    async def stop_step(self, step_id: str) -> bool:
        async with self._lock:
            if not self.busy or self.current_step_id != step_id:
                if self.last_step_id == step_id and self.last_step_status in {
                    StepStatus.SUCCEEDED,
                    StepStatus.FAILED,
                    StepStatus.CANCELLED,
                    StepStatus.SKIPPED,
                }:
                    return True
                return False
            self._stop_event.set()
            plugin = self._active_plugin
            logger.info("收到停止任务请求 step_id={}", step_id)
        if plugin:
            try:
                await plugin.stop(step_id)
            except Exception:
                pass
        return True

    async def _run_task(self, request: StepExecutionRequest) -> None:
        if self._send_message is None or self._request_message is None:
            raise RuntimeError("step manager transport is not configured")
        final_status = StepStatus.FAILED
        logger.info(
            "任务开始执行 step_id={} plugin_id={} mode={} sampling_strategy={}",
            request.step_id,
            request.plugin_id,
            request.mode,
            (request.resolved_params.get("sampling") or {}).get("strategy") if isinstance(request.resolved_params.get("sampling"), dict) else request.query_strategy,
        )
        try:
            result = await StepPipelineRunner(manager=self, request=request).run()
            final_status = result.status
        except asyncio.CancelledError:
            final_status = await self._publish_cancelled_result(request)
        except Exception as exc:
            if self._stop_event.is_set():
                final_status = await self._publish_cancelled_result(request)
            else:
                final_status = await self._publish_failed_result(request, exc)
        finally:
            await self._reset_after_task(request.step_id, final_status)

    def _ensure_reporter(self, request: StepExecutionRequest) -> StepReporter:
        workspace = Workspace(
            self.runs_dir,
            request.step_id,
            round_id=request.round_id,
            attempt=request.attempt,
        )
        workspace.ensure()
        if not workspace.config_path.exists():
            workspace.write_config(request.raw_payload)
        return StepReporter(request.step_id, workspace.events_path)

    async def _publish_cancelled_result(self, request: StepExecutionRequest) -> StepStatus:
        if self._send_message is None:
            raise RuntimeError("step manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.step_id,
            reporter.status(StepStatus.CANCELLED.value, "step cancelled"),
        )
        await self._send_message(
            runtime_codec.build_step_result_message(
                request_id=str(uuid.uuid4()),
                step_id=request.step_id,
                status=StepStatus.CANCELLED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message="cancelled by request",
            )
        )
        logger.warning("任务被取消 step_id={}", request.step_id)
        return StepStatus.CANCELLED

    async def _publish_failed_result(self, request: StepExecutionRequest, exc: Exception) -> StepStatus:
        if self._send_message is None:
            raise RuntimeError("step manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        if isinstance(exc, StepPipelineError):
            error_message = exc.to_user_message()
        else:
            error_message = (
                f"[{StepErrorCode.INTERNAL_ERROR.value}] {str(exc)} "
                f"(stage={StepStage.EXECUTE.value})"
            )
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.step_id,
            reporter.status(StepStatus.FAILED.value, error_message),
        )
        await self._send_message(
            runtime_codec.build_step_result_message(
                request_id=str(uuid.uuid4()),
                step_id=request.step_id,
                status=StepStatus.FAILED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message=error_message,
            )
        )
        logger.exception("任务执行失败 step_id={} error={}", request.step_id, error_message)
        return StepStatus.FAILED

    async def _reset_after_task(self, step_id: str, final_status: StepStatus) -> None:
        async with self._lock:
            self.executor_state = ExecutorState.IDLE
            self.last_step_id = step_id
            self.last_step_status = final_status
            self.current_step_id = None
            self._task = None
            self._stop_event.clear()
            self._active_plugin = None
        logger.info("任务收尾完成 step_id={} final_status={}", step_id, final_status.value)

    async def _request_upload_ticket(
        self,
        *,
        step_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        return await self._data_gateway.request_upload_ticket(
            step_id=step_id,
            artifact_name=artifact_name,
            content_type=content_type,
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

    async def _push_event(self, step_id: str, event: dict[str, Any]) -> None:
        if self._send_message is None:
            raise RuntimeError("step manager send transport is not configured")
        await self._send_message(
            runtime_codec.build_step_event_message(
                request_id=str(uuid.uuid4()),
                step_id=step_id,
                seq=int(event["seq"]),
                ts=int(event["ts"]),
                event_type=str(event["event_type"]),
                payload=event["payload"] or {},
            )
        )

    async def _fetch_all(
        self,
        step_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        return await self._data_gateway.fetch_all(
            step_id=step_id,
            query_type=query_type,
            project_id=project_id,
            commit_id=commit_id,
            limit=limit,
            stop_event=self._stop_event,
        )

    async def _fetch_page(
        self,
        *,
        step_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        cursor: str | None,
        limit: int,
    ) -> FetchedPage:
        return await self._data_gateway.fetch_page(
            step_id=step_id,
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
        step_id: str,
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
            step_id=step_id,
            project_id=project_id,
            commit_id=commit_id,
            strategy=strategy,
            params=params,
            protected=protected,
            query_type=query_type,
            topk=topk,
            context=context,
        )
