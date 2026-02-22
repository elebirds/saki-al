from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.plugins.ipc.proxy_plugin import SubprocessPluginProxy
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
    _ORCHESTRATOR_ONLY_STEP_TYPES = {
        "select",
        "activate_samples",
        "advance_branch",
    }
    _TRAINING_PIPELINE_STEP_TYPES = {
        "train",
        "score",
        "eval",
        "export",
        "upload_artifact",
        "custom",
    }
    _TRAIN_AND_SAMPLE_STEP_TYPES = {
        "train",
        "custom",
    }
    _SCORE_ONLY_STEP_TYPES = {
        "score",
    }
    _TRAIN_ONLY_STEP_TYPES = {
        "eval",
        "export",
        "upload_artifact",
    }

    def __init__(self, *, manager: StepManager, request: StepExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._task_id = request.step_id
        self._effective_plugin_params: dict[str, Any] = {}

    async def run(self) -> StepFinalResult:
        self._validate_request()
        metadata_plugin = self._resolve_plugin()
        workspace, reporter, emitter = self._prepare_workspace()
        plugin = self._build_execution_plugin(metadata_plugin=metadata_plugin, emitter=emitter)
        await self._emit_start_status(emitter)

        metrics: dict[str, Any]
        artifacts: dict[str, Any]
        candidates: list[dict[str, Any]]
        optional_upload_failures: list[str]

        try:
            if self._request.step_type in self._SCORE_ONLY_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_score_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                )
            elif self._request.step_type in self._TRAIN_ONLY_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_train_only_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                )
            elif self._request.step_type in self._TRAIN_AND_SAMPLE_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_train_and_sample_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                )
            else:
                raise RuntimeError(f"step_type routing is not implemented: {self._request.step_type}")

            return await self._finalize_result(
                reporter=reporter,
                metrics=metrics,
                artifacts=artifacts,
                candidates=candidates,
                optional_upload_failures=optional_upload_failures,
            )
        finally:
            await self._shutdown_plugin(plugin)

    def _validate_request(self) -> None:
        if self._request.mode not in self._SUPPORTED_MODES:
            raise RuntimeError(f"unsupported mode: {self._request.mode}")
        if self._request.dispatch_kind == "orchestrator":
            raise RuntimeError(f"orchestrator step should not be dispatched to executor: {self._request.step_id}")
        if self._request.step_type in self._ORCHESTRATOR_ONLY_STEP_TYPES:
            raise RuntimeError(
                f"step_type '{self._request.step_type}' must be handled by dispatcher orchestrator"
            )
        if self._request.step_type not in self._TRAINING_PIPELINE_STEP_TYPES:
            raise RuntimeError(f"unsupported step_type for executor pipeline: {self._request.step_type}")

    def _resolve_plugin(self):
        plugin = self._manager.plugin_registry.get(self._request.plugin_id)
        if not plugin:
            raise RuntimeError(f"plugin not found: {self._request.plugin_id}")
        self._manager.plugin_registry.ensure_worker_loadable(self._request.plugin_id)
        supported_step_types = {
            str(item).strip().lower()
            for item in (plugin.supported_step_types or [])
            if str(item).strip()
        }
        if supported_step_types and self._request.step_type not in supported_step_types:
            raise RuntimeError(
                f"plugin {self._request.plugin_id} does not support step_type={self._request.step_type}; "
                f"supported={sorted(supported_step_types)}"
            )
        raw_plugin_config = self._request.resolved_params.get("plugin")
        if not isinstance(raw_plugin_config, dict):
            raw_plugin_config = dict(self._request.resolved_params)
        plugin_config = plugin.resolve_config(self._request.mode, raw_plugin_config)
        # Inject runtime seeds / round metadata – produce a plain dict for
        # IPC-serialisable downstream consumption.
        effective_plugin_params = plugin_config.to_dict()
        for key in ("split_seed", "train_seed", "sampling_seed", "round_index", "deterministic"):
            if key in self._request.resolved_params and key not in effective_plugin_params:
                effective_plugin_params[key] = self._request.resolved_params.get(key)
        plugin.validate_params(effective_plugin_params)
        self._effective_plugin_params = effective_plugin_params
        return plugin

    def _build_execution_plugin(self, *, metadata_plugin: Any, emitter: StepEventEmitter):
        # Extract external plugin info if available
        python_executable = getattr(metadata_plugin, "python_path", None)
        entrypoint_module = getattr(metadata_plugin, "entrypoint", None)

        plugin = SubprocessPluginProxy(
            metadata_plugin=metadata_plugin,
            step_id=self._request.step_id,
            emit=emitter.emit,
            python_executable=python_executable,
            entrypoint_module=entrypoint_module,
        )
        self._manager._active_plugin = plugin  # noqa: SLF001
        return plugin

    async def _shutdown_plugin(self, plugin: Any) -> None:
        shutdown = getattr(plugin, "shutdown", None)
        if callable(shutdown):
            await shutdown()

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
        await emitter.emit_status(StepStatus.DISPATCHING, "step dispatching")
        await emitter.emit_status(StepStatus.RUNNING, "step running")

    async def _run_training_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
    ) -> tuple[Any, set[str]]:
        protected = await self._prepare_plugin_data(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
        )
        output = await plugin.train(workspace, self._effective_plugin_params, emitter.emit)
        return output, protected

    async def _prepare_plugin_data(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
    ) -> set[str]:
        params_snapshot = {
            "yolo_task": self._effective_plugin_params.get("yolo_task"),
            "epochs": self._effective_plugin_params.get("epochs"),
            "batch": self._effective_plugin_params.get("batch", self._effective_plugin_params.get("batch_size")),
            "imgsz": self._effective_plugin_params.get("imgsz"),
            "model_source": self._effective_plugin_params.get("model_source"),
            "model_preset": self._effective_plugin_params.get("model_preset"),
            "split_seed": self._request.resolved_params.get("split_seed"),
            "train_seed": self._request.resolved_params.get("train_seed"),
            "sampling_seed": self._request.resolved_params.get("sampling_seed"),
            "mode": self._request.mode,
            "step_type": self._request.step_type,
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
        prepare_data = getattr(plugin, "prepare_data")
        # Inject plugin-specific config into splits for prepare_data.
        # This avoids changing the prepare_data interface across the entire chain.
        splits = dict(data_bundle.splits)
        for _inject_key in ("yolo_task",):
            if _inject_key in self._effective_plugin_params:
                splits[_inject_key] = self._effective_plugin_params[_inject_key]
        try:
            await prepare_data(
                workspace=workspace,
                labels=data_bundle.labels,
                samples=data_bundle.samples,
                annotations=data_bundle.train_annotations,
                dataset_ir=data_bundle.ir_batch,
                splits=splits,
            )
        except TypeError:
            await prepare_data(
                workspace,
                data_bundle.labels,
                data_bundle.samples,
                data_bundle.train_annotations,
                data_bundle.ir_batch,
            )
        return data_bundle.protected

    async def _run_train_and_sample_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
        reporter: StepReporter,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
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
        return output.metrics, artifacts, candidates, optional_upload_failures

    async def _run_train_only_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
        reporter: StepReporter,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        output, _protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, [], optional_upload_failures

    async def _run_score_pipeline(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        protected = await self._prepare_plugin_data(
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
        metrics: dict[str, Any] = {
            "score_candidate_count": float(len(candidates)),
        }
        return metrics, {}, candidates, []

    async def _collect_candidates(
        self,
        *,
        plugin: Any,
        workspace: Workspace,
        emitter: StepEventEmitter,
        protected: set[str],
    ) -> list[dict[str, Any]]:
        skip_sampling = bool(self._request.resolved_params.get("skip_sampling", False))
        if self._request.mode == "manual":
            await emitter.emit("log", {"level": "INFO", "message": "manual mode: skip sampling"})
            return []
        if skip_sampling:
            await emitter.emit("log", {"level": "INFO", "message": "skip_sampling=true, TopK sampling skipped"})
            return []

        sampling_cfg = self._request.resolved_params.get("sampling")
        sampling_cfg = dict(sampling_cfg) if isinstance(sampling_cfg, dict) else {}
        strategy = str(
            sampling_cfg.get("strategy")
            or self._request.query_strategy
            or ""
        ).strip()
        if not strategy:
            await emitter.emit("log", {"level": "INFO", "message": "sampling strategy is empty, skip sampling"})
            return []
        topk = int(sampling_cfg.get("topk", self._request.resolved_params.get("topk", 200)))
        sampling_params = dict(self._effective_plugin_params)
        sampling_params.update(sampling_cfg)
        sampling_params["sampling_topk"] = topk
        sampling_params["sampling_seed"] = int(
            self._request.resolved_params.get("sampling_seed", sampling_params.get("sampling_seed", 0))
        )
        return await self._manager._collect_topk_candidates_streaming(  # noqa: SLF001
            plugin=plugin,
            workspace=workspace,
            step_id=self._request.step_id,
            project_id=self._request.project_id,
            commit_id=self._request.input_commit_id,
            strategy=strategy,
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
