from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.jobs.contracts import JobExecutionRequest, JobFinalResult
from saki_executor.jobs.orchestration.event_emitter import JobEventEmitter
from saki_executor.jobs.orchestration.training_data_service import TrainingDataService
from saki_executor.jobs.state import ExecutorState, JobStatus
from saki_executor.jobs.workspace import Workspace
from saki_executor.sdk.reporter import JobReporter

if TYPE_CHECKING:
    from saki_executor.jobs.manager import JobManager


class JobPipelineRunner:
    _SUPPORTED_MODES = {"active_learning", "simulation"}

    def __init__(self, *, manager: JobManager, request: JobExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._job_id = request.job_id

    async def run(self) -> JobFinalResult:
        self._validate_request()
        plugin = self._resolve_plugin()
        workspace, reporter, emitter = self._prepare_workspace()
        await self._emit_start_status(emitter)

        output, protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
        )
        candidates = await self._collect_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return await self._finalize_result(
            reporter=reporter,
            metrics=output.metrics,
            artifacts=artifacts,
            candidates=candidates,
            optional_upload_failures=optional_upload_failures,
        )

    def _validate_request(self) -> None:
        if self._request.mode not in self._SUPPORTED_MODES:
            raise RuntimeError(f"unsupported mode: {self._request.mode}")

    def _resolve_plugin(self):
        plugin = self._manager.plugin_registry.get(self._request.plugin_id)
        if not plugin:
            raise RuntimeError(f"plugin not found: {self._request.plugin_id}")
        plugin.validate_params(self._request.params)
        self._manager._active_plugin = plugin  # noqa: SLF001
        return plugin

    def _prepare_workspace(self) -> tuple[Workspace, JobReporter, JobEventEmitter]:
        workspace = Workspace(self._manager.runs_dir, self._job_id)
        workspace.ensure()
        workspace.write_config(self._request.raw_payload)
        reporter = JobReporter(self._job_id, workspace.events_path)

        async def _push_event(event: dict[str, Any]) -> None:
            await self._manager._push_event(self._job_id, event)  # noqa: SLF001

        emitter = JobEventEmitter(
            reporter=reporter,
            stop_event=self._manager._stop_event,  # noqa: SLF001
            push_event=_push_event,
        )
        return workspace, reporter, emitter

    async def _emit_start_status(self, emitter: JobEventEmitter) -> None:
        self._manager.executor_state = ExecutorState.RUNNING
        await emitter.emit_status(JobStatus.CREATED, "job created")
        await emitter.emit_status(JobStatus.QUEUED, "job queued")
        await emitter.emit_status(JobStatus.RUNNING, "job running")

    async def _run_training_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: JobEventEmitter,
    ) -> tuple[Any, set[str]]:
        data_service = TrainingDataService(
            fetch_all=self._manager._fetch_all,  # noqa: SLF001
            cache=self._manager.cache,
            stop_event=self._manager._stop_event,  # noqa: SLF001
            normalize_simulation_ratio_schedule=self._manager._normalize_simulation_ratio_schedule,  # noqa: SLF001
            resolve_simulation_ratio=lambda iteration, schedule: self._manager._resolve_simulation_ratio(  # noqa: SLF001
                iteration=iteration,
                schedule=schedule,
            ),
        )
        data_bundle = await data_service.prepare(
            request=self._request,
            plugin=plugin,
            emit=emitter.emit,
        )
        await plugin.prepare_data(
            workspace,
            data_bundle.labels,
            data_bundle.train_samples,
            data_bundle.train_annotations,
        )
        output = await plugin.train(workspace, self._request.params, emitter.emit)
        return output, data_bundle.protected

    async def _collect_candidates(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: JobEventEmitter,
        protected: set[str],
    ) -> list[dict[str, Any]]:
        if self._request.mode != "active_learning":
            await emitter.emit(
                "log",
                {"level": "INFO", "message": "simulation mode skips active-learning TopK sampling"},
            )
            return []
        topk = int(self._request.params.get("topk", 200))
        sampling_params = dict(self._request.params)
        sampling_params["topk"] = topk
        return await self._manager._collect_topk_candidates_streaming(  # noqa: SLF001
            plugin=plugin,
            workspace=workspace,
            job_id=self._request.job_id,
            project_id=self._request.project_id,
            commit_id=self._request.source_commit_id,
            strategy=self._request.query_strategy,
            params=sampling_params,
            protected=protected,
            topk=topk,
        )

    async def _finalize_result(
        self,
        *,
        reporter: JobReporter,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        optional_upload_failures: list[str],
    ) -> JobFinalResult:
        self._manager.executor_state = ExecutorState.FINALIZING
        if optional_upload_failures:
            reason = "optional artifact upload failed: " + "; ".join(optional_upload_failures)
            await self._manager._push_event(  # noqa: SLF001
                self._job_id,
                reporter.status(JobStatus.PARTIAL_FAILED.value, reason),
            )
            await self._send_result(
                status=JobStatus.PARTIAL_FAILED,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=reason,
            )
            logger.warning("任务部分成功（非关键制品上传失败） job_id={} reason={}", self._job_id, reason)
            return JobFinalResult(
                job_id=self._job_id,
                status=JobStatus.PARTIAL_FAILED,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=reason,
            )
        await self._manager._push_event(  # noqa: SLF001
            self._job_id,
            reporter.status(JobStatus.SUCCEEDED.value, "job succeeded"),
        )
        await self._send_result(
            status=JobStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
        )
        logger.info("任务执行成功 job_id={}", self._job_id)
        return JobFinalResult(
            job_id=self._job_id,
            status=JobStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
            error_message="",
        )

    async def _upload_artifacts(
        self,
        *,
        output_artifacts: list[Any],
        reporter: JobReporter,
    ) -> tuple[dict[str, Any], list[str]]:
        artifacts: dict[str, Any] = {}
        optional_upload_failures: list[str] = []
        for artifact in output_artifacts:
            artifact_path = Path(artifact.path)
            required = bool(getattr(artifact, "required", False))
            try:
                ticket = await self._manager._request_upload_ticket(  # noqa: SLF001
                    job_id=self._job_id,
                    artifact_name=artifact.name,
                    content_type=artifact.content_type,
                )
                upload_url = ticket.upload_url
                storage_uri = ticket.storage_uri
                headers = dict(ticket.headers)
                size = artifact_path.stat().st_size
                await self._manager._upload_artifact_with_retry(  # noqa: SLF001
                    artifact_path=artifact_path,
                    upload_url=upload_url,
                    headers=headers,
                )
            except Exception as exc:
                message = f"artifact={artifact.name} required={required} error={exc}"
                if required:
                    raise RuntimeError(f"required artifact upload failed: {message}") from exc
                optional_upload_failures.append(message)
                logger.warning("非关键制品上传失败，忽略并继续 job_id={} {}", self._job_id, message)
                continue

            artifacts[artifact.name] = {
                "kind": artifact.kind,
                "uri": storage_uri,
                "meta": artifact.meta or {"size": size},
            }
            await self._manager._push_event(  # noqa: SLF001
                self._job_id,
                reporter.artifact(
                    kind=artifact.kind,
                    name=artifact.name,
                    uri=storage_uri,
                    meta=artifact.meta or {"size": size},
                ),
            )

        return artifacts, optional_upload_failures

    async def _send_result(
        self,
        *,
        status: JobStatus,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        error_message: str = "",
    ) -> None:
        if self._manager._send_message is None:  # noqa: SLF001
            raise RuntimeError("job manager send transport is not configured")
        await self._manager._send_message(  # noqa: SLF001
            runtime_codec.build_job_result_message(
                request_id=str(uuid.uuid4()),
                job_id=self._job_id,
                status=status.value,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=error_message,
            )
        )
