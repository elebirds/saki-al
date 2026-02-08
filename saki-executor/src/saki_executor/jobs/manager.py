from __future__ import annotations

import asyncio
import heapq
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.contracts import ArtifactUploadTicket, FetchedPage, JobExecutionRequest
from saki_executor.jobs.orchestration.runner import JobPipelineRunner
from saki_executor.jobs.state import ExecutorState, JobStatus
from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.sdk.reporter import JobReporter

SendFn = Callable[[pb.RuntimeMessage], Awaitable[None]]
RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage]]


UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_BACKOFF_SEC = (1.0, 2.0)


class JobManager:
    def __init__(
            self,
            runs_dir: str,
            cache: AssetCache,
            plugin_registry: PluginRegistry,
            send_message: SendFn | None = None,
            request_message: RequestFn | None = None,
    ) -> None:
        self.runs_dir = runs_dir
        self.cache = cache
        self.plugin_registry = plugin_registry
        self._send_message = send_message
        self._request_message = request_message

        self.executor_state = ExecutorState.IDLE
        self.current_job_id: str | None = None
        self.last_job_id: str | None = None
        self.last_job_status: JobStatus | None = None
        self._active_plugin: ExecutorPlugin | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

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
            "current_job_id": self.current_job_id,
            "last_job_id": self.last_job_id,
            "last_job_status": self.last_job_status.value if self.last_job_status else None,
        }

    async def assign_job(self, request_id: str, payload: dict[str, Any]) -> bool:
        request = JobExecutionRequest.from_payload(payload)
        async with self._lock:
            if self.busy:
                logger.warning("拒绝任务分配：executor busy, request_id={}", request_id)
                return False
            self.current_job_id = request.job_id
            self.executor_state = ExecutorState.RESERVED
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_job(request))
            logger.info(
                "接受任务分配 request_id={} job_id={} plugin_id={}",
                request_id,
                self.current_job_id,
                request.plugin_id,
            )
            return True

    async def stop_job(self, job_id: str) -> bool:
        async with self._lock:
            if not self.busy or self.current_job_id != job_id:
                if self.last_job_id == job_id and self.last_job_status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.PARTIAL_FAILED,
                    JobStatus.STOPPED,
                }:
                    return True
                return False
            self._stop_event.set()
            plugin = self._active_plugin
            logger.info("收到停止任务请求 job_id={}", job_id)
        if plugin:
            try:
                await plugin.stop(job_id)
            except Exception:
                # Best-effort stop hook for plugin-owned subprocess/resources.
                pass
        return True

    async def _run_job(self, request: JobExecutionRequest) -> None:
        if self._send_message is None or self._request_message is None:
            raise RuntimeError("job manager transport is not configured")
        final_status = JobStatus.FAILED
        logger.info(
            "任务开始执行 job_id={} plugin_id={} mode={} query_strategy={}",
            request.job_id,
            request.plugin_id,
            request.mode,
            request.query_strategy,
        )
        try:
            result = await JobPipelineRunner(manager=self, request=request).run()
            final_status = result.status
        except asyncio.CancelledError:
            final_status = await self._publish_stopped_result(request)
        except Exception as exc:
            final_status = await self._publish_failed_result(request, exc)
        finally:
            await self._reset_after_job(request.job_id, final_status)

    def _ensure_reporter(self, request: JobExecutionRequest) -> JobReporter:
        workspace = Workspace(self.runs_dir, request.job_id)
        workspace.ensure()
        if not workspace.config_path.exists():
            workspace.write_config(request.raw_payload)
        return JobReporter(request.job_id, workspace.events_path)

    async def _publish_stopped_result(self, request: JobExecutionRequest) -> JobStatus:
        if self._send_message is None:
            raise RuntimeError("job manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.job_id,
            reporter.status(JobStatus.STOPPED.value, "job stopped"),
        )
        await self._send_message(
            runtime_codec.build_job_result_message(
                request_id=str(uuid.uuid4()),
                job_id=request.job_id,
                status=JobStatus.STOPPED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message="stopped by request",
            )
        )
        logger.warning("任务被停止 job_id={}", request.job_id)
        return JobStatus.STOPPED

    async def _publish_failed_result(self, request: JobExecutionRequest, exc: Exception) -> JobStatus:
        if self._send_message is None:
            raise RuntimeError("job manager send transport is not configured")
        self.executor_state = ExecutorState.FINALIZING
        reporter = self._ensure_reporter(request)
        await self._push_event(
            request.job_id,
            reporter.status(JobStatus.FAILED.value, str(exc)),
        )
        await self._send_message(
            runtime_codec.build_job_result_message(
                request_id=str(uuid.uuid4()),
                job_id=request.job_id,
                status=JobStatus.FAILED.value,
                metrics={},
                artifacts={},
                candidates=[],
                error_message=str(exc),
            )
        )
        logger.exception("任务执行失败 job_id={} error={}", request.job_id, exc)
        return JobStatus.FAILED

    async def _reset_after_job(self, job_id: str, final_status: JobStatus) -> None:
        async with self._lock:
            self.executor_state = ExecutorState.IDLE
            self.last_job_id = job_id
            self.last_job_status = final_status
            self.current_job_id = None
            self._task = None
            self._stop_event.clear()
            self._active_plugin = None
        logger.info("任务收尾完成 job_id={} final_status={}", job_id, final_status.value)

    async def _request_upload_ticket(
            self,
            *,
            job_id: str,
            artifact_name: str,
            content_type: str,
    ) -> ArtifactUploadTicket:
        if self._request_message is None:
            raise RuntimeError("job manager request transport is not configured")
        ticket_response = await self._request_message(
            runtime_codec.build_upload_ticket_request_message(
                request_id=str(uuid.uuid4()),
                job_id=job_id,
                artifact_name=artifact_name,
                content_type=content_type,
            )
        )
        payload_type = ticket_response.WhichOneof("payload")
        if payload_type == "error":
            error_payload = runtime_codec.parse_error(ticket_response.error)
            raise RuntimeError(str(error_payload.get("error") or "upload ticket request failed"))
        if payload_type != "upload_ticket_response":
            raise RuntimeError(f"unexpected upload ticket response payload: {payload_type}")
        return ArtifactUploadTicket.from_dict(
            runtime_codec.parse_upload_ticket_response(ticket_response.upload_ticket_response)
        )

    async def _upload_artifact_with_retry(
            self,
            *,
            artifact_path: Path,
            upload_url: str,
            headers: dict[str, str],
    ) -> None:
        if not upload_url:
            raise RuntimeError("upload url is empty")
        payload = await asyncio.to_thread(artifact_path.read_bytes)
        request_headers = dict(headers)
        if not any(str(key).lower() == "content-length" for key in request_headers):
            request_headers["Content-Length"] = str(len(payload))
        attempt = 0
        last_error: Exception | None = None
        while attempt < UPLOAD_MAX_ATTEMPTS:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.put(
                        upload_url,
                        content=payload,
                        headers=request_headers,
                    )
                    status_code = int(response.status_code)
                    if 400 <= status_code < 500:
                        logger.error(
                            "制品上传失败（不可重试） artifact={} attempt={} status={}",
                            artifact_path.name,
                            attempt,
                            status_code,
                        )
                        response.raise_for_status()
                    response.raise_for_status()
                logger.info(
                    "制品上传成功 artifact={} attempt={} status={}",
                    artifact_path.name,
                    attempt,
                    int(response.status_code),
                )
                return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = int(exc.response.status_code) if exc.response is not None else 0
                logger.warning(
                    "制品上传失败 artifact={} attempt={} status={} error={}",
                    artifact_path.name,
                    attempt,
                    status_code,
                    type(exc).__name__,
                )
                if 400 <= status_code < 500:
                    raise RuntimeError(
                        f"upload failed with non-retryable status={status_code} artifact={artifact_path.name}"
                    ) from exc
                if attempt >= UPLOAD_MAX_ATTEMPTS:
                    break
                backoff = UPLOAD_RETRY_BACKOFF_SEC[min(attempt - 1, len(UPLOAD_RETRY_BACKOFF_SEC) - 1)]
                await asyncio.sleep(backoff)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "制品上传异常 artifact={} attempt={} error={}",
                    artifact_path.name,
                    attempt,
                    type(exc).__name__,
                )
                if attempt >= UPLOAD_MAX_ATTEMPTS:
                    break
                backoff = UPLOAD_RETRY_BACKOFF_SEC[min(attempt - 1, len(UPLOAD_RETRY_BACKOFF_SEC) - 1)]
                await asyncio.sleep(backoff)
        raise RuntimeError(
            f"upload failed after {UPLOAD_MAX_ATTEMPTS} attempts artifact={artifact_path.name}"
        ) from last_error

    async def _push_event(self, job_id: str, event: dict[str, Any]) -> None:
        if self._send_message is None:
            raise RuntimeError("job manager send transport is not configured")
        await self._send_message(
            runtime_codec.build_job_event_message(
                request_id=str(uuid.uuid4()),
                job_id=job_id,
                seq=int(event["seq"]),
                ts=int(event["ts"]),
                event_type=str(event["event_type"]),
                payload=event["payload"] or {},
            )
        )

    async def _fetch_all(
            self,
            job_id: str,
            query_type: str,
            project_id: str,
            commit_id: str,
            limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if self._request_message is None:
            raise RuntimeError("job manager request transport is not configured")

        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            response = await self._fetch_page(
                job_id=job_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=limit,
            )
            chunk = response.items
            items.extend(chunk)
            cursor = response.next_cursor
            if not cursor:
                break
            if self._stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")
        return items

    async def _fetch_page(
            self,
            *,
            job_id: str,
            query_type: str,
            project_id: str,
            commit_id: str,
            cursor: str | None,
            limit: int,
    ) -> FetchedPage:
        if self._request_message is None:
            raise RuntimeError("job manager request transport is not configured")

        response_message = await self._request_message(
            runtime_codec.build_data_request_message(
                request_id=str(uuid.uuid4()),
                job_id=job_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=limit,
            )
        )
        payload_type = response_message.WhichOneof("payload")
        if payload_type == "error":
            error_payload = runtime_codec.parse_error(response_message.error)
            raise RuntimeError(str(error_payload.get("error") or "data request failed"))
        if payload_type != "data_response":
            raise RuntimeError(f"unexpected data response payload: {payload_type}")
        return FetchedPage.from_dict(runtime_codec.parse_data_response(response_message.data_response))

    async def _collect_topk_candidates_streaming(
            self,
            *,
            plugin: ExecutorPlugin,
            workspace: Workspace,
            job_id: str,
            project_id: str,
            commit_id: str,
            strategy: str,
            params: dict[str, Any],
            protected: set[str],
            topk: int,
    ) -> list[dict[str, Any]]:
        page_size = max(1, min(5000, int(params.get("unlabeled_page_size", 1000))))
        target_topk = max(1, topk)
        cursor: str | None = None
        heap: list[tuple[float, int, dict[str, Any]]] = []
        counter = 0

        while True:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")

            response = await self._fetch_page(
                job_id=job_id,
                query_type="unlabeled_samples",
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=page_size,
            )
            chunk = response.items
            if not chunk and not response.next_cursor:
                break

            # Download current page samples on demand, avoiding full-dataset prefetch.
            for item in chunk:
                asset_hash = item.get("asset_hash")
                download_url = item.get("download_url")
                if not asset_hash or not download_url:
                    continue
                cached_path = await self.cache.ensure_cached(
                    str(asset_hash),
                    str(download_url),
                    protected=protected,
                    pin_job_id=job_id,
                )
                item["local_path"] = str(cached_path)
                protected.add(str(asset_hash))

            batch = await plugin.predict_unlabeled_batch(
                workspace=workspace,
                unlabeled_samples=chunk,
                strategy=strategy,
                params=params,
            )
            for candidate in batch or []:
                sample_id = str(candidate.get("sample_id") or "")
                if not sample_id:
                    continue
                try:
                    score = float(candidate.get("score") or 0.0)
                except Exception:
                    score = 0.0
                reason_payload = candidate.get("reason") or {}
                if not isinstance(reason_payload, dict):
                    reason_payload = {}
                prediction_snapshot = candidate.get("prediction_snapshot")
                if isinstance(prediction_snapshot, dict) and prediction_snapshot:
                    reason_payload = {**reason_payload, "prediction_snapshot": prediction_snapshot}
                payload = {
                    "sample_id": sample_id,
                    "score": score,
                    "reason": reason_payload,
                }
                counter += 1
                key = (score, counter, payload)
                if len(heap) < target_topk:
                    heapq.heappush(heap, key)
                else:
                    smallest = heap[0]
                    if score > smallest[0]:
                        heapq.heapreplace(heap, key)

            cursor = response.next_cursor
            if not cursor:
                break

        ranked = sorted(heap, key=lambda item: item[0], reverse=True)
        output: list[dict[str, Any]] = []
        for rank, item in enumerate(ranked, start=1):
            payload = item[2]
            reason = payload.get("reason")
            if isinstance(reason, dict):
                payload["reason"] = {**reason, "rank": rank}
            output.append(payload)
        return output

    @staticmethod
    def _normalize_simulation_ratio_schedule(raw: Any) -> list[float]:
        default_schedule = [0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
        if not isinstance(raw, list):
            return default_schedule

        values: list[float] = []
        for item in raw:
            try:
                ratio = float(item)
            except Exception:
                continue
            values.append(max(0.0, min(1.0, ratio)))
        return values or default_schedule

    @staticmethod
    def _resolve_simulation_ratio(*, iteration: int, schedule: list[float]) -> float:
        if not schedule:
            return 1.0
        if iteration <= 1:
            return float(schedule[0])
        index = min(len(schedule) - 1, max(0, iteration - 1))
        return float(schedule[index])
