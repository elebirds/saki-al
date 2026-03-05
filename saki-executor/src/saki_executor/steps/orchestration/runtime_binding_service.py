from __future__ import annotations

from pathlib import Path
from typing import Any

from saki_executor.plugins.venv_manager import ensure_plugin_venv_for_profile
from saki_executor.runtime.binding.device_binding_resolver import DeviceBindingResolver
from saki_executor.steps.orchestration.error_codes import StepErrorCode, StepStage, wrap_stage_error
from saki_executor.steps.orchestration.models import BoundExecutionPlan, StepExecutionPlan
from saki_plugin_sdk import ExecutionBindingContext, RuntimeCapabilitySnapshot


class RuntimeBindingService:
    def __init__(self) -> None:
        self._binding_resolver = DeviceBindingResolver()

    def ensure_profile_environment(
        self,
        *,
        plan: StepExecutionPlan,
        auto_sync: bool,
    ) -> StepExecutionPlan:
        metadata_plugin = plan.metadata_plugin
        selected_profile = plan.selected_profile
        try:
            plugin_dir = getattr(metadata_plugin, "plugin_dir", None)
            if plugin_dir:
                worker_python = ensure_plugin_venv_for_profile(
                    plugin_dir=Path(str(plugin_dir)),
                    plugin_id=str(getattr(metadata_plugin, "plugin_id", plan.request.plugin_id) or plan.request.plugin_id),
                    plugin_version=str(getattr(metadata_plugin, "version", "0.0.0") or "0.0.0"),
                    profile=selected_profile,
                    auto_sync=auto_sync,
                )
            else:
                worker_python = getattr(metadata_plugin, "python_path", None)

            entrypoint_module = getattr(metadata_plugin, "entrypoint", None)
            if selected_profile.entrypoint:
                entrypoint_module = selected_profile.entrypoint
            extra_env = dict(selected_profile.env)
            return plan.with_runtime_environment(
                worker_python=worker_python,
                entrypoint_module=entrypoint_module,
                extra_env=extra_env,
            )
        except Exception as exc:
            raise wrap_stage_error(
                stage=StepStage.SYNCING_ENV,
                default_code=StepErrorCode.ENV_SYNC_FAILED,
                exc=exc,
                message=(
                    f"profile environment sync failed plugin_id={plan.request.plugin_id} "
                    f"task_id={plan.request.task_id}: {exc}"
                ),
            ) from exc

    async def probe_runtime_capability(
        self,
        *,
        plan: StepExecutionPlan,
        plugin: Any,
    ) -> RuntimeCapabilitySnapshot:
        try:
            runtime_capability = await plugin.probe_runtime_capability(context=plan.runtime_context)
            if isinstance(runtime_capability, RuntimeCapabilitySnapshot):
                return runtime_capability
            return RuntimeCapabilitySnapshot.from_dict(dict(runtime_capability or {}))
        except Exception as exc:
            raise wrap_stage_error(
                stage=StepStage.PROBING_RUNTIME,
                default_code=StepErrorCode.RUNTIME_PROBE_FAILED,
                exc=exc,
                message=(
                    f"runtime capability probe failed plugin_id={plan.request.plugin_id} "
                    f"task_id={plan.request.task_id}: {exc}"
                ),
            ) from exc

    async def bind_execution_context(
        self,
        *,
        plan: StepExecutionPlan,
        plugin: Any,
        runtime_capability: RuntimeCapabilitySnapshot,
    ) -> BoundExecutionPlan:
        try:
            binding = self._binding_resolver.resolve(
                requested_device=plan.effective_plugin_params.get("device", "auto"),
                host_capability=plan.host_capability,
                runtime_capability=runtime_capability,
                supported_backends=list(getattr(plugin, "supported_accelerators", []) or []),
                profile=plan.selected_profile,
                allow_auto_fallback=bool(getattr(plugin, "supports_auto_fallback", True)),
            )
        except Exception as exc:
            raise wrap_stage_error(
                stage=StepStage.BINDING_DEVICE,
                default_code=StepErrorCode.DEVICE_BINDING_CONFLICT,
                exc=exc,
                message=(
                    f"device binding failed plugin_id={plan.request.plugin_id} "
                    f"task_id={plan.request.task_id}: {exc}"
                ),
            ) from exc

        bound_params = dict(plan.effective_plugin_params)

        execution_context = ExecutionBindingContext(
            step_context=plan.runtime_context,
            host_capability=plan.host_capability,
            runtime_capability=runtime_capability,
            device_binding=binding,
            profile_id=plan.selected_profile.id,
        )

        bind_context = getattr(plugin, "bind_execution_context", None)
        if callable(bind_context):
            try:
                await bind_context(execution_context)
            except Exception as exc:
                raise wrap_stage_error(
                    stage=StepStage.BINDING_DEVICE,
                    default_code=StepErrorCode.BIND_CONTEXT_FAILED,
                    exc=exc,
                    message=(
                        f"bind execution context failed plugin_id={plan.request.plugin_id} "
                        f"task_id={plan.request.task_id}: {exc}"
                    ),
                ) from exc

        try:
            plugin.validate_params(bound_params, context=execution_context)
        except Exception as exc:
            raise wrap_stage_error(
                stage=StepStage.POST_BIND_VALIDATION,
                default_code=StepErrorCode.PARAM_VALIDATE_FAILED,
                exc=exc,
                message=(
                    f"plugin params validate failed after binding plugin_id={plan.request.plugin_id} "
                    f"task_id={plan.request.task_id}: {exc}"
                ),
            ) from exc

        return BoundExecutionPlan(
            plan=plan,
            runtime_capability=runtime_capability,
            execution_context=execution_context,
            effective_plugin_params=bound_params,
        )
