from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.core.config import settings
from saki_executor.plugins.ipc.proxy_plugin import SubprocessPluginProxy
from saki_executor.steps.contracts import SUPPORTED_LOOP_MODES, StepExecutionRequest, StepFinalResult
from saki_executor.steps.orchestration.error_codes import StepErrorCode, StepPipelineError, StepStage, wrap_stage_error
from saki_executor.steps.orchestration.event_emitter import StepEventEmitter
from saki_executor.steps.orchestration.models import BoundExecutionPlan, StepExecutionPlan
from saki_executor.steps.orchestration.pipeline_stage_service import PipelineStageService
from saki_executor.steps.orchestration.plugin_resolution_service import PluginResolutionService
from saki_executor.steps.orchestration.runtime_binding_service import RuntimeBindingService
from saki_executor.steps.state import ExecutorState, StepStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.steps.workspace_adapter import WorkspaceAdapter
from saki_plugin_sdk import StepReporter

if TYPE_CHECKING:
    from saki_executor.steps.manager import StepManager


class StepPipelineRunner:
    _SUPPORTED_MODES = SUPPORTED_LOOP_MODES
    _ORCHESTRATOR_ONLY_STEP_TYPES = {"select"}
    _TRAINING_PIPELINE_STEP_TYPES = {"train", "score", "eval", "predict", "custom"}

    def __init__(self, *, manager: StepManager, request: StepExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._task_id = request.step_id
        self._plugin_resolution_service = PluginResolutionService()
        self._runtime_binding_service = RuntimeBindingService()
        self._pipeline_stage_service = PipelineStageService(manager=manager, request=request)

    async def run(self) -> StepFinalResult:
        self._validate_request()
        workspace, reporter, emitter = self._prepare_workspace()
        await self._emit_dispatching_status(emitter)

        plan = await self._resolve_execution_plan(emitter)
        plan = await self._sync_profile_environment(plan=plan, emitter=emitter)
        plugin = self._build_execution_plugin(plan=plan, emitter=emitter)

        try:
            bound_plan = await self._prepare_execution_binding(plan=plan, plugin=plugin, emitter=emitter)
            await self._emit_running_status(emitter)

            runtime_requirements = plugin.get_step_runtime_requirements(self._request.step_type)
            await self._pipeline_stage_service.prepare_trained_model_if_needed(
                workspace=workspace,
                emitter=emitter,
                runtime_requirements=runtime_requirements,
                bound_plan=bound_plan,
            )
            metrics, artifacts, candidates, optional_upload_failures = await self._pipeline_stage_service.execute(
                plugin=plugin,
                workspace=workspace,
                emitter=emitter,
                reporter=reporter,
                runtime_requirements=runtime_requirements,
                bound_plan=bound_plan,
            )

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
        try:
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
        except Exception as exc:
            raise wrap_stage_error(
                stage=StepStage.REQUEST_VALIDATION,
                default_code=StepErrorCode.REQUEST_INVALID,
                exc=exc,
                message=f"request validation failed step_id={self._request.step_id}: {exc}",
            ) from exc

    async def _resolve_execution_plan(self, emitter: StepEventEmitter) -> StepExecutionPlan:
        await emitter.emit_stage_start(
            stage=StepStage.PLUGIN_RESOLUTION.value,
            message=f"resolving plugin and runtime plan plugin_id={self._request.plugin_id}",
        )
        try:
            plan = self._plugin_resolution_service.resolve(manager=self._manager, request=self._request)
        except StepPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        except Exception as exc:
            wrapped = wrap_stage_error(
                stage=StepStage.PLUGIN_RESOLUTION,
                default_code=StepErrorCode.INTERNAL_ERROR,
                exc=exc,
                message=f"plugin resolution failed step_id={self._request.step_id}: {exc}",
            )
            await emitter.emit_stage_fail(
                stage=wrapped.stage.value,
                error_code=wrapped.code.value,
                message=wrapped.message,
            )
            raise wrapped

        await emitter.emit_stage_success(
            stage=StepStage.PLUGIN_RESOLUTION.value,
            message=(
                f"runtime plan resolved profile={plan.selected_profile.id} "
                f"step_id={self._request.step_id}"
            ),
        )
        return plan

    async def _sync_profile_environment(
        self,
        *,
        plan: StepExecutionPlan,
        emitter: StepEventEmitter,
    ) -> StepExecutionPlan:
        await emitter.emit_status(StepStatus.SYNCING_ENV, "syncing plugin runtime environment")
        await emitter.emit_stage_start(
            stage=StepStage.SYNCING_ENV.value,
            message=f"ensuring runtime profile environment profile={plan.selected_profile.id}",
        )
        try:
            synced = self._runtime_binding_service.ensure_profile_environment(
                plan=plan,
                auto_sync=settings.PLUGIN_VENV_AUTO_SYNC,
            )
        except StepPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        except Exception as exc:
            wrapped = wrap_stage_error(
                stage=StepStage.SYNCING_ENV,
                default_code=StepErrorCode.ENV_SYNC_FAILED,
                exc=exc,
                message=f"runtime environment sync failed step_id={self._request.step_id}: {exc}",
            )
            await emitter.emit_stage_fail(
                stage=wrapped.stage.value,
                error_code=wrapped.code.value,
                message=wrapped.message,
            )
            raise wrapped

        await emitter.emit_stage_success(
            stage=StepStage.SYNCING_ENV.value,
            message=f"runtime profile environment ready profile={plan.selected_profile.id}",
        )
        return synced

    def _build_execution_plugin(self, *, plan: StepExecutionPlan, emitter: StepEventEmitter):
        plugin = SubprocessPluginProxy(
            metadata_plugin=plan.metadata_plugin,
            step_id=self._request.step_id,
            emit=emitter.emit,
            python_executable=plan.worker_python or getattr(plan.metadata_plugin, "python_path", None),
            entrypoint_module=plan.entrypoint_module or getattr(plan.metadata_plugin, "entrypoint", None),
            extra_env=dict(plan.extra_env),
        )
        self._manager._active_plugin = plugin  # noqa: SLF001
        return plugin

    async def _prepare_execution_binding(
        self,
        *,
        plan: StepExecutionPlan,
        plugin: Any,
        emitter: StepEventEmitter,
    ) -> BoundExecutionPlan:
        await emitter.emit_status(StepStatus.PROBING_RUNTIME, "probing plugin runtime capability")
        await emitter.emit_stage_start(
            stage=StepStage.PROBING_RUNTIME.value,
            message=f"probing runtime capability profile={plan.selected_profile.id}",
        )
        try:
            runtime_capability = await self._runtime_binding_service.probe_runtime_capability(
                plan=plan,
                plugin=plugin,
            )
        except StepPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        await emitter.emit_stage_success(
            stage=StepStage.PROBING_RUNTIME.value,
            message="runtime capability probe succeeded",
        )

        await emitter.emit_status(StepStatus.BINDING_DEVICE, "binding execution device")
        await emitter.emit_stage_start(
            stage=StepStage.BINDING_DEVICE.value,
            message="resolving device binding",
        )
        try:
            bound_plan = await self._runtime_binding_service.bind_execution_context(
                plan=plan,
                plugin=plugin,
                runtime_capability=runtime_capability,
            )
        except StepPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise

        await emitter.emit_stage_success(
            stage=StepStage.BINDING_DEVICE.value,
            message=(
                f"execution binding resolved backend={bound_plan.execution_context.device_binding.backend} "
                f"profile={plan.selected_profile.id}"
            ),
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "execution capability snapshots "
                    f"host_capability={plan.host_capability.to_dict()} "
                    f"runtime_capability={runtime_capability.to_dict()} "
                    f"selected_profile={plan.selected_profile.to_dict()} "
                    f"device_binding={bound_plan.execution_context.device_binding.to_dict()}"
                ),
            },
        )
        return bound_plan

    async def _shutdown_plugin(self, plugin: Any) -> None:
        shutdown = getattr(plugin, "shutdown", None)
        if callable(shutdown):
            await shutdown()

    def _prepare_workspace(self) -> tuple[WorkspaceAdapter, StepReporter, StepEventEmitter]:
        raw_workspace = Workspace(
            self._manager.runs_dir,
            self._task_id,
            round_id=self._request.round_id,
            attempt=self._request.attempt,
        )
        workspace = WorkspaceAdapter(raw_workspace)
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

    async def _emit_dispatching_status(self, emitter: StepEventEmitter) -> None:
        self._manager.executor_state = ExecutorState.RUNNING
        await emitter.emit_status(StepStatus.DISPATCHING, "step dispatching")

    async def _emit_running_status(self, emitter: StepEventEmitter) -> None:
        await emitter.emit_status(StepStatus.RUNNING, "step running")

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
