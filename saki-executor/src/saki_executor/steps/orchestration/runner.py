from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.agent import codec as runtime_codec
from saki_executor.core.config import settings
from saki_executor.plugins.ipc.proxy_plugin import SubprocessPluginProxy
from saki_executor.steps.contracts import SUPPORTED_LOOP_MODES, TaskExecutionRequest, TaskFinalResult
from saki_executor.steps.orchestration.error_codes import TaskErrorCode, TaskPipelineError, TaskStage, wrap_task_error
from saki_executor.steps.orchestration.event_emitter import TaskEventEmitter
from saki_executor.steps.orchestration.models import BoundExecutionPlan, TaskExecutionPlan
from saki_executor.steps.orchestration.pipeline_stage_service import PipelineStageService
from saki_executor.steps.orchestration.plugin_resolution_service import PluginResolutionService
from saki_executor.steps.orchestration.runtime_binding_service import RuntimeBindingService
from saki_executor.steps.state import ExecutorState, TaskStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.steps.workspace_adapter import WorkspaceAdapter
from saki_plugin_sdk import TaskReporter

if TYPE_CHECKING:
    from saki_executor.steps.manager import TaskManager


class TaskPipelineRunner:
    _SUPPORTED_MODES = SUPPORTED_LOOP_MODES
    _ORCHESTRATOR_ONLY_TASK_TYPES = {"select"}
    _TRAINING_PIPELINE_TASK_TYPES = {"train", "score", "eval", "predict", "custom"}

    def __init__(self, *, manager: TaskManager, request: TaskExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._task_id = request.task_id
        self._plugin_resolution_service = PluginResolutionService()
        self._runtime_binding_service = RuntimeBindingService()
        self._pipeline_stage_service = PipelineStageService(manager=manager, request=request)

    async def run(self) -> TaskFinalResult:
        self._validate_request()
        workspace, reporter, emitter = self._prepare_workspace()
        await self._emit_dispatching_status(emitter)

        plan = await self._resolve_execution_plan(emitter, workspace)
        plan = await self._sync_profile_environment(plan=plan, emitter=emitter)
        plugin = self._build_execution_plugin(plan=plan, emitter=emitter)

        try:
            bound_plan = await self._prepare_execution_binding(plan=plan, plugin=plugin, emitter=emitter)
            await self._emit_running_status(emitter)

            runtime_requirements = plugin.get_task_runtime_requirements(self._request.task_type)
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
                raise RuntimeError(f"不支持的模式: {self._request.mode}")
            if self._request.dispatch_kind == "orchestrator":
                raise RuntimeError(
                    f"orchestrator 任务不应派发到 executor: {self._request.task_id}"
                )
            if self._request.task_type in self._ORCHESTRATOR_ONLY_TASK_TYPES:
                raise RuntimeError(
                    f"task_type '{self._request.task_type}' 必须由 dispatcher orchestrator 处理"
                )
            if self._request.task_type not in self._TRAINING_PIPELINE_TASK_TYPES:
                raise RuntimeError(f"executor 流水线不支持的 task_type: {self._request.task_type}")
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.REQUEST_VALIDATION,
                default_code=TaskErrorCode.REQUEST_INVALID,
                exc=exc,
                message=f"请求校验失败 task_id={self._request.task_id}: {exc}",
            ) from exc

    async def _resolve_execution_plan(
        self,
        emitter: TaskEventEmitter,
        workspace: WorkspaceAdapter,
    ) -> TaskExecutionPlan:
        await emitter.emit_stage_start(
            stage=TaskStage.PLUGIN_RESOLUTION.value,
            message=f"正在解析插件与运行计划 plugin_id={self._request.plugin_id}",
        )
        try:
            await self._materialize_request_runtime_artifacts_if_needed(
                workspace=workspace,
                emitter=emitter,
            )
            plan = self._plugin_resolution_service.resolve(manager=self._manager, request=self._request)
        except TaskPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        except Exception as exc:
            wrapped = wrap_task_error(
                stage=TaskStage.PLUGIN_RESOLUTION,
                default_code=TaskErrorCode.INTERNAL_ERROR,
                exc=exc,
                message=f"插件解析失败 task_id={self._request.task_id}: {exc}",
            )
            await emitter.emit_stage_fail(
                stage=wrapped.stage.value,
                error_code=wrapped.code.value,
                message=wrapped.message,
            )
            raise wrapped

        await emitter.emit_stage_success(
            stage=TaskStage.PLUGIN_RESOLUTION.value,
            message=(
                f"运行计划解析完成 profile={plan.selected_profile.id} "
                f"task_id={self._request.task_id}"
            ),
        )
        return plan

    async def _materialize_request_runtime_artifacts_if_needed(
        self,
        *,
        workspace: WorkspaceAdapter,
        emitter: TaskEventEmitter,
    ) -> None:
        metadata_plugin = self._manager.plugin_registry.get(self._request.plugin_id)
        if metadata_plugin is None:
            return
        get_runtime_requirements = getattr(metadata_plugin, "get_task_runtime_requirements", None)
        if not callable(get_runtime_requirements):
            return
        try:
            runtime_requirements = get_runtime_requirements(self._request.task_type)
            updated_request = await self._pipeline_stage_service.materialize_request_runtime_model_if_needed(
                workspace=workspace,
                emitter=emitter,
                runtime_requirements=runtime_requirements,
                request=self._request,
            )
        except TaskPipelineError:
            raise
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.PLUGIN_RESOLUTION,
                default_code=TaskErrorCode.EXECUTION_FAILED,
                exc=exc,
                message=f"运行时模型引用物化失败 task_id={self._request.task_id}: {exc}",
            ) from exc
        if updated_request is self._request:
            return
        self._request = updated_request
        self._pipeline_stage_service = PipelineStageService(manager=self._manager, request=updated_request)
        workspace.write_config(updated_request.raw_payload)

    async def _sync_profile_environment(
        self,
        *,
        plan: TaskExecutionPlan,
        emitter: TaskEventEmitter,
    ) -> TaskExecutionPlan:
        await emitter.emit_status(TaskStatus.SYNCING_ENV, "正在同步插件运行环境")
        await emitter.emit_stage_start(
            stage=TaskStage.SYNCING_ENV.value,
            message=f"正在确保运行时配置环境 profile={plan.selected_profile.id}",
        )
        try:
            synced = self._runtime_binding_service.ensure_profile_environment(
                plan=plan,
                auto_sync=settings.PLUGIN_VENV_AUTO_SYNC,
            )
        except TaskPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        except Exception as exc:
            wrapped = wrap_task_error(
                stage=TaskStage.SYNCING_ENV,
                default_code=TaskErrorCode.ENV_SYNC_FAILED,
                exc=exc,
                message=f"运行时环境同步失败 task_id={self._request.task_id}: {exc}",
            )
            await emitter.emit_stage_fail(
                stage=wrapped.stage.value,
                error_code=wrapped.code.value,
                message=wrapped.message,
            )
            raise wrapped

        await emitter.emit_stage_success(
            stage=TaskStage.SYNCING_ENV.value,
            message=f"运行时配置环境就绪 profile={plan.selected_profile.id}",
        )
        return synced

    def _build_execution_plugin(self, *, plan: TaskExecutionPlan, emitter: TaskEventEmitter):
        plugin = SubprocessPluginProxy(
            metadata_plugin=plan.metadata_plugin,
            task_id=self._request.task_id,
            emit=emitter.emit,
            mark_activity=self._manager.mark_local_activity,
            python_executable=plan.worker_python or getattr(plan.metadata_plugin, "python_path", None),
            entrypoint_module=plan.entrypoint_module or getattr(plan.metadata_plugin, "entrypoint", None),
            extra_env=dict(plan.extra_env),
        )
        self._manager.set_active_plugin(plugin)
        return plugin

    async def _prepare_execution_binding(
        self,
        *,
        plan: TaskExecutionPlan,
        plugin: Any,
        emitter: TaskEventEmitter,
    ) -> BoundExecutionPlan:
        await emitter.emit_status(TaskStatus.PROBING_RUNTIME, "正在探测插件运行能力")
        await emitter.emit_stage_start(
            stage=TaskStage.PROBING_RUNTIME.value,
            message=f"正在探测运行能力 profile={plan.selected_profile.id}",
        )
        try:
            runtime_capability = await self._runtime_binding_service.probe_runtime_capability(
                plan=plan,
                plugin=plugin,
            )
        except TaskPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise
        await emitter.emit_stage_success(
            stage=TaskStage.PROBING_RUNTIME.value,
            message="运行能力探测成功",
        )

        await emitter.emit_status(TaskStatus.BINDING_DEVICE, "正在绑定执行设备")
        await emitter.emit_stage_start(
            stage=TaskStage.BINDING_DEVICE.value,
            message="正在解析设备绑定",
        )
        try:
            bound_plan = await self._runtime_binding_service.bind_execution_context(
                plan=plan,
                plugin=plugin,
                runtime_capability=runtime_capability,
            )
        except TaskPipelineError as exc:
            await emitter.emit_stage_fail(
                stage=exc.stage.value,
                error_code=exc.code.value,
                message=exc.message,
            )
            raise

        await emitter.emit_stage_success(
            stage=TaskStage.BINDING_DEVICE.value,
            message=(
                f"执行绑定解析完成 backend={bound_plan.execution_context.device_binding.backend} "
                f"profile={plan.selected_profile.id}"
            ),
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "执行能力快照 "
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

    def _prepare_workspace(self) -> tuple[WorkspaceAdapter, TaskReporter, TaskEventEmitter]:
        raw_workspace = Workspace(
            self._manager.runs_dir,
            self._task_id,
            round_id=self._request.round_id,
            attempt=self._request.attempt,
            prepared_data_cache_root=self._manager.cache.root / "prepared_data_v2",
        )
        workspace = WorkspaceAdapter(raw_workspace)
        workspace.ensure()
        workspace.write_config(self._request.raw_payload)
        reporter = TaskReporter(self._task_id, workspace.events_path)

        async def _push_event(event: dict[str, Any]) -> None:
            self._manager.mark_local_activity(f"task_event:{str(event.get('event_type') or '')}")
            await self._manager.push_task_event(self._task_id, event)

        emitter = TaskEventEmitter(
            reporter=reporter,
            stop_event=self._manager.stop_event,
            push_event=_push_event,
        )
        return workspace, reporter, emitter

    async def _emit_dispatching_status(self, emitter: TaskEventEmitter) -> None:
        self._manager.executor_state = ExecutorState.RUNNING
        await emitter.emit_status(TaskStatus.DISPATCHING, "任务派发中")

    async def _emit_running_status(self, emitter: TaskEventEmitter) -> None:
        await emitter.emit_status(TaskStatus.RUNNING, "任务执行中")

    async def _finalize_result(
        self,
        *,
        reporter: TaskReporter,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        optional_upload_failures: list[str],
    ) -> TaskFinalResult:
        self._manager.executor_state = ExecutorState.FINALIZING
        warnings: list[str] = []
        if optional_upload_failures:
            warnings.append("可选制品上传失败: " + "; ".join(optional_upload_failures))
        reporter.status(TaskStatus.SUCCEEDED.value, "任务成功")
        await self._send_result(
            status=TaskStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
            warnings=warnings,
        )
        if warnings:
            logger.warning("任务成功但存在 warning task_id={} warnings={}", self._task_id, warnings)
        else:
            logger.info("任务执行成功 task_id={}", self._task_id)
        return TaskFinalResult(
            task_id=self._task_id,
            status=TaskStatus.SUCCEEDED,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
            error_message="",
            warnings=warnings,
        )

    async def _send_result(
        self,
        *,
        status: TaskStatus,
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        candidates: list[dict[str, Any]],
        error_message: str = "",
        warnings: list[str] | None = None,
    ) -> None:
        result_messages = runtime_codec.build_task_result_message(
            request_id=str(uuid.uuid4()),
            task_id=self._task_id,
            execution_id=self._request.execution_id,
            status=status.value,
            metrics=metrics,
            artifacts=artifacts,
            candidates=candidates,
            error_message=error_message,
            warnings=warnings,
        )
        if len(result_messages) > 1:
            serialized_bytes = sum(len(message.task_result_chunk.payload_chunk) for message in result_messages)
            logger.info(
                "任务结果启用分块回传 task_id={} execution_id={} mode=chunked_task_result serialized_bytes={} chunk_count={} candidate_count={}",
                self._task_id,
                self._request.execution_id,
                serialized_bytes,
                len(result_messages),
                len(candidates),
            )
        for message in result_messages:
            await self._manager.send_runtime_message(message)
