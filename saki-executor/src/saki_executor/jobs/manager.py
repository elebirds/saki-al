from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.contracts import ArtifactUploadTicket, FetchedPage, TaskExecutionRequest
from saki_executor.jobs.orchestration.runner import JobPipelineRunner
from saki_executor.jobs.services import ArtifactUploader, DataGateway, SamplingService
from saki_executor.jobs.state import ExecutorState, TaskStatus
from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.sdk.reporter import JobReporter

SendFn = Callable[[pb.RuntimeMessage], Awaitable[None]]
RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage]]
HttpClientFactory = Callable[..., Any]


class JobManager:
    def __init__(
        self,
        runs_dir: str,
        cache: AssetCache,
        plugin_registry: PluginRegistry,
        send_message: SendFn | None = None,
        request_message: RequestFn | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.cache = cache
        self.plugin_registry = plugin_registry
        self._send_message = send_message
        self._request_message = request_message

        self.executor_state = ExecutorState.IDLE
        self.current_task_id: str | None = None
        self.last_task_id: str | None = None
        self.last_task_status: TaskStatus | None = None
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
            "current_task_id": self.current_task_id,
            "last_task_id": self.last_task_id,
            "last_task_status": self.last_task_status.value if self.last_task_status else None,
        }

    async def assign_task(self, request_id: str, payload: dict[str, Any]) -> bool:
        request = TaskExecutionRequest.from_payload(payload)
        async with self._lock:
            if self.busy:
                logger.warning("拒绝任务分配：executor busy, request_id={}", request_id)
                return False
            self.current_task_id = request.task_id
            self.executor_state = ExecutorState.RESERVED
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_task(request))
            logger.info(
                "接受任务分配 request_id={} task_id={} plugin_id={}",
                request_id,
                self.current_task_id,
                request.plugin_id,
            )
            return True

    async def stop_task(self, task_id: str) -> bool:
        async with self._lock:
            if not self.busy or self.current_task_id != task_id:
                if self.last_task_id == task_id and self.last_task_status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.SKIPPED,
                }:
                    return True
                return False
            self._stop_event.set()
            plugin = self._active_plugin
            logger.info("收到停止任务请求 task_id={}", task_id)
        if plugin:
            try:
                await plugin.stop(task_id)
            except Exception:
                pass
        return True

    async def _run_task(self, request: TaskExecutionRequest) -> None:
        if self._send_message is None or self._request_message is None:
            raise RuntimeError("task manager transport is not configured")
        final_status = TaskStatus.FAILED
        logger.info(
            "任务开始执行 task_id={} plugin_id={} mode={} query_strategy={}",
            request.task_id,
            request.plugin_id,
            request.mode,
            request.query_strategy,
        )
        try:
            result = await JobPipelineRunner(manager=self, request=request).run()
            final_status = result.status
        except asyncio.CancelledError:
            final_status = await self._publish_cancelled_result(request)
        except Exception as exc:
            final_status = await self._publish_failed_result(request, exc)
        finally:
            await self._reset_after_task(request.task_id, final_status)

    def _ensure_reporter(self, request: TaskExecutionRequest) -> JobReporter:
        workspace = Workspace(self.runs_dir, request.task_id)
        workspace.ensure()
        if not workspace.config_path.exists():
            workspace.write_config(request.raw_payload)
        return JobReporter(request.task_id, workspace.events_path)

    async def _publish_cancelled_result(self, request: TaskExecutionRequest) -> TaskStatus:
        if self._send_message is None:
            raise RuntimeError("task manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.task_id,
            reporter.status(TaskStatus.CANCELLED.value, "task cancelled"),
        )
        await self._send_message(
            runtime_codec.build_task_result_message(
                request_id=str(uuid.uuid4()),
                task_id=request.task_id,
                status=TaskStatus.CANCELLED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message="cancelled by request",
            )
        )
        logger.warning("任务被取消 task_id={}", request.task_id)
        return TaskStatus.CANCELLED

    async def _publish_failed_result(self, request: TaskExecutionRequest, exc: Exception) -> TaskStatus:
        if self._send_message is None:
            raise RuntimeError("task manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.task_id,
            reporter.status(TaskStatus.FAILED.value, str(exc)),
        )
        await self._send_message(
            runtime_codec.build_task_result_message(
                request_id=str(uuid.uuid4()),
                task_id=request.task_id,
                status=TaskStatus.FAILED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message=str(exc),
            )
        )
        logger.exception("任务执行失败 task_id={} error={}", request.task_id, exc)
        return TaskStatus.FAILED

    async def _reset_after_task(self, task_id: str, final_status: TaskStatus) -> None:
        async with self._lock:
            self.executor_state = ExecutorState.IDLE
            self.last_task_id = task_id
            self.last_task_status = final_status
            self.current_task_id = None
            self._task = None
            self._stop_event.clear()
            self._active_plugin = None
        logger.info("任务收尾完成 task_id={} final_status={}", task_id, final_status.value)

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
            raise RuntimeError("task manager send transport is not configured")
        await self._send_message(
            runtime_codec.build_task_event_message(
                request_id=str(uuid.uuid4()),
                task_id=task_id,
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
        workspace: Workspace,
        task_id: str,
        project_id: str,
        commit_id: str,
        strategy: str,
        params: dict[str, Any],
        protected: set[str],
        topk: int,
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
            topk=topk,
        )
