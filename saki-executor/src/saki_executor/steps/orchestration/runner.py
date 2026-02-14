from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.steps.contracts import SUPPORTED_LOOP_MODES, StepExecutionRequest, StepFinalResult
from saki_executor.steps.orchestration.event_emitter import StepEventEmitter
from saki_executor.steps.orchestration.training_data_service import TrainingDataService
from saki_executor.steps.state import ExecutorState, StepStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.sdk.reporter import StepReporter

if TYPE_CHECKING:
    from saki_executor.steps.manager import StepManager


class StepPipelineRunner:
    _SUPPORTED_MODES = SUPPORTED_LOOP_MODES

    def __init__(self, *, manager: StepManager, request: StepExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._task_id = request.step_id

    async def run(self) -> StepFinalResult:
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
        plugin.validate_params(self._request.resolved_params)
        self._manager._active_plugin = plugin  # noqa: SLF001
        return plugin

    def _prepare_workspace(self) -> tuple[Workspace, StepReporter, StepEventEmitter]:
        workspace = Workspace(self._manager.runs_dir, self._task_id)
        workspace.ensure()
        workspace.write_config(self._request.raw_payload)
        reporter = StepReporter(self._task_id, workspace.events_path)

        async def _push_event(event: dict[str, Any]) -> None:
            await self._manager._push_event(self._task_id, event)  # noqa: SLF001

        emitter = StepEventEmitter(
            reporter=reporter,
            stop_event=self._manager._stop_event,  # noqa: SLF001
            push_event=_push_event,
        )
        return workspace, reporter, emitter

    async def _emit_start_status(self, emitter: StepEventEmitter) -> None:
        self._manager.executor_state = ExecutorState.RUNNING
        await emitter.emit_status(StepStatus.PENDING, "step pending")
        await emitter.emit_status(StepStatus.DISPATCHING, "step dispatching")
        await emitter.emit_status(StepStatus.RUNNING, "step running")

    async def _run_training_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
    ) -> tuple[Any, set[str]]:
        params_snapshot = {
            "epochs": self._request.resolved_params.get("epochs"),
            "batch": self._request.resolved_params.get("batch", self._request.resolved_params.get("batch_size")),
            "imgsz": self._request.resolved_params.get("imgsz"),
            "base_model": self._request.resolved_params.get("base_model"),
            "split_seed": self._request.resolved_params.get("split_seed"),
            "random_seed": self._request.resolved_params.get("random_seed"),
            "mode": self._request.mode,
            "round_index": self._request.round_index,
            "step_id": self._request.step_id,
        }
        await emitter.emit("log", {"level": "INFO", "message": f"effective training params: {params_snapshot}"})
        data_service = TrainingDataService(
            fetch_all=self._manager._fetch_all,  # noqa: SLF001
            cache=self._manager.cache,
            stop_event=self._manager._stop_event,  # noqa: SLF001
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
        output = await plugin.train(workspace, self._request.resolved_params, emitter.emit)
        return output, data_bundle.protected

    async def _collect_candidates(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
        protected: set[str],
    ) -> list[dict[str, Any]]:
        skip_sampling = bool(self._request.resolved_params.get("skip_sampling", False))
        if skip_sampling:
            await emitter.emit("log", {"level": "INFO", "message": "skip_sampling=true, TopK sampling skipped"})
            return []
        topk = int(self._request.resolved_params.get("topk", 200))
        sampling_params = dict(self._request.resolved_params)
        sampling_params["topk"] = topk
        return await self._manager._collect_topk_candidates_streaming(  # noqa: SLF001
            plugin=plugin,
            workspace=workspace,
            step_id=self._request.step_id,
            project_id=self._request.project_id,
            commit_id=self._request.input_commit_id,
            strategy=self._request.query_strategy,
            params=sampling_params,
            protected=protected,
            topk=topk,
        )

    async def _finalize_result(
        self,
        *,
        reporter: StepReporter,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        optional_upload_failures: list[str],
    ) -> StepFinalResult:
        self._manager.executor_state = ExecutorState.FINALIZING
        if optional_upload_failures:
            reason = "optional artifact upload failed: " + "; ".join(optional_upload_failures)
            await self._manager._push_event(self._task_id, reporter.status(StepStatus.FAILED.value, reason))  # noqa: SLF001
            await self._send_result(
                status=StepStatus.FAILED,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=reason,
            )
            logger.warning("任务部分成功（制品上传失败） step_id={} reason={}", self._task_id, reason)
            return StepFinalResult(
                step_id=self._task_id,
                status=StepStatus.FAILED,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=reason,
            )
        await self._manager._push_event(self._task_id, reporter.status(StepStatus.SUCCEEDED.value, "step succeeded"))  # noqa: SLF001
        await self._send_result(
            status=StepStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
        )
        logger.info("任务执行成功 step_id={}", self._task_id)
        return StepFinalResult(
            step_id=self._task_id,
            status=StepStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
            error_message="",
        )

    async def _upload_artifacts(
        self,
        *,
        output_artifacts: list[Any],
        reporter: StepReporter,
    ) -> tuple[dict[str, Any], list[str]]:
        artifacts: dict[str, Any] = {}
        optional_upload_failures: list[str] = []
        for artifact in output_artifacts:
            artifact_path = Path(artifact.path)
            required = bool(getattr(artifact, "required", False))
            try:
                ticket = await self._manager._request_upload_ticket(  # noqa: SLF001
                    step_id=self._task_id,
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
                logger.warning("非关键制品上传失败，忽略并继续 step_id={} {}", self._task_id, message)
                continue

            artifacts[artifact.name] = {
                "kind": artifact.kind,
                "uri": storage_uri,
                "meta": artifact.meta or {"size": size},
            }
            await self._manager._push_event(  # noqa: SLF001
                self._task_id,
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
        status: StepStatus,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        error_message: str = "",
    ) -> None:
        if self._manager._send_message is None:  # noqa: SLF001
            raise RuntimeError("step manager send transport is not configured")
        await self._manager._send_message(  # noqa: SLF001
            runtime_codec.build_step_result_message(
                request_id=str(uuid.uuid4()),
                step_id=self._task_id,
                status=status.value,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                error_message=error_message,
            )
        )
