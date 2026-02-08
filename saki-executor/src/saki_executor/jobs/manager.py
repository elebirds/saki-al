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
        async with self._lock:
            if self.busy:
                logger.warning("拒绝任务分配：executor busy, request_id={}", request_id)
                return False
            self.current_job_id = str(payload.get("job_id") or "")
            self.executor_state = ExecutorState.RESERVED
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_job(payload))
            logger.info(
                "接受任务分配 request_id={} job_id={} plugin_id={}",
                request_id,
                self.current_job_id,
                str(payload.get("plugin_id") or ""),
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

    async def _run_job(self, payload: dict[str, Any]) -> None:
        if self._send_message is None or self._request_message is None:
            raise RuntimeError("job manager transport is not configured")

        job_id = str(payload.get("job_id") or "")
        plugin_id = str(payload.get("plugin_id") or "")
        params = payload.get("params") or {}
        project_id = str(payload.get("project_id") or "")
        source_commit_id = str(payload.get("source_commit_id") or "")
        query_strategy = str(payload.get("query_strategy") or "uncertainty_1_minus_max_conf")
        mode = str(payload.get("mode") or "active_learning").lower()
        raw_iteration = payload.get("iteration")
        try:
            iteration = int(raw_iteration)
        except Exception:
            iteration = 1
        if iteration <= 0:
            iteration = 1
        final_status = JobStatus.FAILED
        logger.info(
            "任务开始执行 job_id={} plugin_id={} mode={} query_strategy={}",
            job_id,
            plugin_id,
            mode,
            query_strategy,
        )

        workspace = Workspace(self.runs_dir, job_id)
        workspace.ensure()
        workspace.write_config(payload)
        reporter = JobReporter(job_id, workspace.events_path)

        async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
            if self._stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")
            if event_type == "log":
                event = reporter.log(level=str(event_payload.get("level", "INFO")), message=str(event_payload.get("message", "")))
            elif event_type == "progress":
                event = reporter.progress(
                    epoch=int(event_payload.get("epoch", 0)),
                    step=int(event_payload.get("step", 0)),
                    total_steps=int(event_payload.get("total_steps", 0)),
                    eta_sec=event_payload.get("eta_sec"),
                )
            elif event_type == "metric":
                metrics = event_payload.get("metrics") or {}
                event = reporter.metric(
                    step=int(event_payload.get("step", 0)),
                    epoch=event_payload.get("epoch"),
                    metrics={str(k): float(v) for k, v in metrics.items()},
                )
            elif event_type == "artifact":
                event = reporter.log(
                    "WARN",
                    (
                        "plugin artifact event is ignored; "
                        f"artifact_name={str(event_payload.get('name', ''))}"
                    ),
                )
            elif event_type == "status":
                event = reporter.status(
                    status=str(event_payload.get("status", JobStatus.RUNNING.value)),
                    reason=event_payload.get("reason"),
                )
            else:
                event = reporter.log("WARN", f"unknown event type: {event_type}")
            await self._push_event(job_id, event)

        try:
            plugin = self.plugin_registry.get(plugin_id)
            if not plugin:
                raise RuntimeError(f"plugin not found: {plugin_id}")
            plugin.validate_params(params)
            self._active_plugin = plugin

            self.executor_state = ExecutorState.RUNNING
            await emit("status", {"status": JobStatus.CREATED.value, "reason": "job created"})
            await emit("status", {"status": JobStatus.QUEUED.value, "reason": "job queued"})
            await emit("status", {"status": JobStatus.RUNNING.value, "reason": "job running"})

            labels = await self._fetch_all(job_id, "labels", project_id, source_commit_id)
            samples = await self._fetch_all(job_id, "samples", project_id, source_commit_id)
            annotations = await self._fetch_all(job_id, "annotations", project_id, source_commit_id)

            train_samples = samples
            train_annotations = annotations
            if mode == "active_learning":
                labeled_sample_ids = {
                    str(item.get("sample_id") or "")
                    for item in annotations
                    if item.get("sample_id")
                }
                if labeled_sample_ids:
                    train_samples = [
                        item for item in samples
                        if str(item.get("id") or "") in labeled_sample_ids
                    ]

            if mode == "simulation":
                schedule = self._normalize_simulation_ratio_schedule(params.get("simulation_ratio_schedule"))
                ratio = self._resolve_simulation_ratio(iteration=iteration, schedule=schedule)
                train_samples, train_annotations = await plugin.select_simulation_subset(
                    samples=samples,
                    annotations=annotations,
                    ratio=ratio,
                    iteration=iteration,
                    params=params,
                )
                await emit(
                    "log",
                    {
                        "level": "INFO",
                        "message": (
                            f"simulation mode enabled iteration={iteration} ratio={ratio:.4f} "
                            f"train_samples={len(train_samples)} train_annotations={len(train_annotations)}"
                        ),
                    },
                )

            # Content-addressed local cache to reduce re-download.
            protected: set[str] = set()
            for item in train_samples:
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

            await plugin.prepare_data(workspace, labels, train_samples, train_annotations)
            output = await plugin.train(workspace, params, emit)

            candidates: list[dict[str, Any]] = []
            if mode == "active_learning":
                topk = int(params.get("topk", 200))
                sampling_params = dict(params)
                sampling_params["topk"] = topk
                candidates = await self._collect_topk_candidates_streaming(
                    plugin=plugin,
                    workspace=workspace,
                    job_id=job_id,
                    project_id=project_id,
                    commit_id=source_commit_id,
                    strategy=query_strategy,
                    params=sampling_params,
                    protected=protected,
                    topk=topk,
                )
            elif mode == "simulation":
                await emit("log", {"level": "INFO", "message": "simulation mode skips active-learning TopK sampling"})
            else:
                raise RuntimeError(f"unsupported mode: {mode}")

            artifacts: dict[str, Any] = {}
            optional_upload_failures: list[str] = []
            for artifact in output.artifacts:
                artifact_path = Path(artifact.path)
                required = bool(getattr(artifact, "required", False))
                try:
                    ticket = await self._request_upload_ticket(
                        job_id=job_id,
                        artifact_name=artifact.name,
                        content_type=artifact.content_type,
                    )
                    upload_url = str(ticket.get("upload_url") or "")
                    storage_uri = str(ticket.get("storage_uri") or "")
                    headers = {
                        str(key): str(value)
                        for key, value in (ticket.get("headers") or {}).items()
                    }
                    size = artifact_path.stat().st_size
                    await self._upload_artifact_with_retry(
                        artifact_path=artifact_path,
                        upload_url=upload_url,
                        headers=headers,
                    )
                except Exception as exc:
                    message = f"artifact={artifact.name} required={required} error={exc}"
                    if required:
                        raise RuntimeError(f"required artifact upload failed: {message}") from exc
                    optional_upload_failures.append(message)
                    logger.warning("非关键制品上传失败，忽略并继续 job_id={} {}", job_id, message)
                    continue

                artifacts[artifact.name] = {
                    "kind": artifact.kind,
                    "uri": storage_uri,
                    "meta": artifact.meta or {"size": size},
                }
                artifact_event = reporter.artifact(
                    kind=artifact.kind,
                    name=artifact.name,
                    uri=storage_uri,
                    meta=artifact.meta or {"size": size},
                )
                await self._push_event(job_id, artifact_event)

            self.executor_state = ExecutorState.FINALIZING
            if optional_upload_failures:
                reason = "optional artifact upload failed: " + "; ".join(optional_upload_failures)
                final_event = reporter.status(JobStatus.PARTIAL_FAILED.value, reason)
                await self._push_event(job_id, final_event)
                await self._send_message(
                    runtime_codec.build_job_result_message(
                        request_id=str(uuid.uuid4()),
                        job_id=job_id,
                        status=JobStatus.PARTIAL_FAILED.value,
                        metrics=output.metrics,
                        artifacts=artifacts,
                        candidates=candidates,
                        error_message=reason,
                    )
                )
                final_status = JobStatus.PARTIAL_FAILED
                logger.warning("任务部分成功（非关键制品上传失败） job_id={} reason={}", job_id, reason)
            else:
                final_event = reporter.status(JobStatus.SUCCEEDED.value, "job succeeded")
                await self._push_event(job_id, final_event)
                await self._send_message(
                    runtime_codec.build_job_result_message(
                        request_id=str(uuid.uuid4()),
                        job_id=job_id,
                        status=JobStatus.SUCCEEDED.value,
                        metrics=output.metrics,
                        artifacts=artifacts,
                        candidates=candidates,
                    )
                )
                final_status = JobStatus.SUCCEEDED
                logger.info("任务执行成功 job_id={}", job_id)
        except asyncio.CancelledError:
            self.executor_state = ExecutorState.FINALIZING
            stop_event = reporter.status(JobStatus.STOPPED.value, "job stopped")
            await self._push_event(job_id, stop_event)
            await self._send_message(
                runtime_codec.build_job_result_message(
                    request_id=str(uuid.uuid4()),
                    job_id=job_id,
                    status=JobStatus.STOPPED.value,
                    metrics={},
                    artifacts={},
                    candidates=[],
                    error_message="stopped by request",
                )
            )
            final_status = JobStatus.STOPPED
            logger.warning("任务被停止 job_id={}", job_id)
        except Exception as exc:
            self.executor_state = ExecutorState.FINALIZING
            fail_event = reporter.status(JobStatus.FAILED.value, str(exc))
            await self._push_event(job_id, fail_event)
            await self._send_message(
                runtime_codec.build_job_result_message(
                    request_id=str(uuid.uuid4()),
                    job_id=job_id,
                    status=JobStatus.FAILED.value,
                    metrics={},
                    artifacts={},
                    candidates=[],
                    error_message=str(exc),
                )
            )
            final_status = JobStatus.FAILED
            logger.exception("任务执行失败 job_id={} error={}", job_id, exc)
        finally:
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
    ) -> dict[str, Any]:
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
        return runtime_codec.parse_upload_ticket_response(ticket_response.upload_ticket_response)

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
            chunk = response.get("items") or []
            items.extend(chunk)
            cursor = response.get("next_cursor")
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
    ) -> dict[str, Any]:
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
        return runtime_codec.parse_data_response(response_message.data_response)

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
            chunk = response.get("items") or []
            if not chunk and not response.get("next_cursor"):
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

            cursor = response.get("next_cursor")
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
