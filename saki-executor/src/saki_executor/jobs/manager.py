from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.jobs.state import ExecutorState, JobStatus
from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.base import ExecutorPlugin
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.sdk.reporter import JobReporter

SendFn = Callable[[dict[str, Any]], Awaitable[None]]
RequestFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


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

    async def assign_job(self, request_id: str, payload: dict[str, Any]) -> bool:
        async with self._lock:
            if self.busy:
                return False
            self.current_job_id = str(payload.get("job_id") or "")
            self.executor_state = ExecutorState.RESERVED
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_job(payload))
            return True

    async def stop_job(self, job_id: str) -> bool:
        async with self._lock:
            if not self.busy or self.current_job_id != job_id:
                if self.last_job_id == job_id and self.last_job_status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.STOPPED,
                }:
                    return True
                return False
            self._stop_event.set()
            plugin = self._active_plugin
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
        final_status = JobStatus.FAILED

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
                event = reporter.artifact(
                    kind=str(event_payload.get("kind", "artifact")),
                    name=str(event_payload.get("name", "")),
                    uri=str(event_payload.get("uri", "")),
                    meta=event_payload.get("meta") or {},
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
            unlabeled = await self._fetch_all(job_id, "unlabeled_samples", project_id, source_commit_id)

            # Content-addressed local cache to reduce re-download.
            protected: set[str] = set()
            for item in samples + unlabeled:
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

            await plugin.prepare_data(workspace, labels, samples, annotations)
            output = await plugin.train(workspace, params, emit)

            topk = int(params.get("topk", 200))
            sampling_params = dict(params)
            sampling_params["topk"] = topk
            candidates = await plugin.predict_unlabeled(workspace, unlabeled, query_strategy, sampling_params)

            artifacts: dict[str, Any] = {}
            for artifact in output.artifacts:
                ticket = await self._request_message(
                    {
                        "type": "upload_ticket_request",
                        "request_id": str(uuid.uuid4()),
                        "job_id": job_id,
                        "artifact_name": artifact.name,
                        "content_type": artifact.content_type,
                    }
                )
                upload_url = str(ticket.get("upload_url") or "")
                storage_uri = str(ticket.get("storage_uri") or "")
                headers = ticket.get("headers") or {}
                data = Path(artifact.path).read_bytes()
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.put(upload_url, content=data, headers=headers)
                    response.raise_for_status()
                artifacts[artifact.name] = {
                    "kind": artifact.kind,
                    "uri": storage_uri,
                    "meta": artifact.meta or {"size": len(data)},
                }

            self.executor_state = ExecutorState.FINALIZING
            final_event = reporter.status(JobStatus.SUCCEEDED.value, "job succeeded")
            await self._push_event(job_id, final_event)
            await self._send_message(
                {
                    "type": "job_result",
                    "request_id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "status": JobStatus.SUCCEEDED.value,
                    "metrics": output.metrics,
                    "artifacts": artifacts,
                    "candidates": candidates,
                }
            )
            final_status = JobStatus.SUCCEEDED
        except asyncio.CancelledError:
            self.executor_state = ExecutorState.FINALIZING
            stop_event = reporter.status(JobStatus.STOPPED.value, "job stopped")
            await self._push_event(job_id, stop_event)
            await self._send_message(
                {
                    "type": "job_result",
                    "request_id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "status": JobStatus.STOPPED.value,
                    "metrics": {},
                    "artifacts": {},
                    "candidates": [],
                    "error_message": "stopped by request",
                }
            )
            final_status = JobStatus.STOPPED
        except Exception as exc:
            self.executor_state = ExecutorState.FINALIZING
            fail_event = reporter.status(JobStatus.FAILED.value, str(exc))
            await self._push_event(job_id, fail_event)
            await self._send_message(
                {
                    "type": "job_result",
                    "request_id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "status": JobStatus.FAILED.value,
                    "metrics": {},
                    "artifacts": {},
                    "candidates": [],
                    "error_message": str(exc),
                }
            )
            final_status = JobStatus.FAILED
        finally:
            async with self._lock:
                self.executor_state = ExecutorState.IDLE
                self.last_job_id = job_id
                self.last_job_status = final_status
                self.current_job_id = None
                self._task = None
                self._stop_event.clear()
                self._active_plugin = None

    async def _push_event(self, job_id: str, event: dict[str, Any]) -> None:
        if self._send_message is None:
            raise RuntimeError("job manager send transport is not configured")
        await self._send_message(
            {
                "type": "job_event",
                "request_id": str(uuid.uuid4()),
                "job_id": job_id,
                "seq": event["seq"],
                "ts": event["ts"],
                "event_type": event["event_type"],
                "payload": event["payload"],
            }
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
            response = await self._request_message(
                {
                    "type": "data_request",
                    "request_id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "query_type": query_type,
                    "project_id": project_id,
                    "commit_id": commit_id,
                    "cursor": cursor,
                    "limit": limit,
                }
            )
            chunk = response.get("items") or []
            items.extend(chunk)
            cursor = response.get("next_cursor")
            if not cursor:
                break
            if self._stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")
        return items
