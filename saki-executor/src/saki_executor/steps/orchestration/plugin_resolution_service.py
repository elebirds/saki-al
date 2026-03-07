from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saki_executor.runtime.profile.profile_selector import ProfileSelectorStrategy
from saki_executor.steps.contracts import TaskExecutionRequest
from saki_executor.steps.orchestration.error_codes import TaskErrorCode, TaskPipelineError, TaskStage, wrap_task_error
from saki_executor.steps.orchestration.models import TaskExecutionPlan
from saki_plugin_sdk import RuntimeProfileSpec, TaskRuntimeContext, parse_runtime_profiles


class PluginResolutionService:
    def __init__(self) -> None:
        self._profile_selector = ProfileSelectorStrategy()

    def resolve(self, *, manager: Any, request: TaskExecutionRequest) -> TaskExecutionPlan:
        metadata_plugin = manager.plugin_registry.get(request.plugin_id)
        if metadata_plugin is None:
            raise TaskPipelineError(
                code=TaskErrorCode.PLUGIN_NOT_FOUND,
                stage=TaskStage.PLUGIN_RESOLUTION,
                message=f"未找到插件: {request.plugin_id}",
            )

        manager.plugin_registry.ensure_worker_loadable(request.plugin_id)
        supported_task_types = {
            str(item).strip().lower()
            for item in (getattr(metadata_plugin, "supported_task_types", []) or [])
            if str(item).strip()
        }
        if supported_task_types and request.task_type not in supported_task_types:
            raise TaskPipelineError(
                code=TaskErrorCode.PLUGIN_UNSUPPORTED_TASK_TYPE,
                stage=TaskStage.PLUGIN_RESOLUTION,
                message=(
                    f"插件 {request.plugin_id} 不支持 task_type={request.task_type}; "
                    f"支持列表={sorted(supported_task_types)}"
                ),
            )

        host_capability = manager.get_host_capability_snapshot()

        raw_plugin_config = request.resolved_params.get("plugin")
        if not isinstance(raw_plugin_config, dict):
            raw_plugin_config = dict(request.resolved_params)

        runtime_context_candidate = self._build_runtime_context(request)
        try:
            resolved_config = metadata_plugin.resolve_config(
                request.mode,
                raw_plugin_config,
                context=runtime_context_candidate.to_dict(),
            )
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.PLUGIN_RESOLUTION,
                default_code=TaskErrorCode.CONFIG_RESOLVE_FAILED,
                exc=exc,
                message=(
                    f"插件配置解析失败 plugin_id={request.plugin_id} "
                    f"task_id={request.task_id}: {exc}"
                ),
            ) from exc

        effective_plugin_params = self._resolved_config_to_dict(resolved_config)
        for key in (
            "split_seed",
            "train_seed",
            "sampling_seed",
            "round_index",
            "deterministic",
            "deterministic_level",
            "strong_deterministic",
        ):
            if key in request.resolved_params and key not in effective_plugin_params:
                effective_plugin_params[key] = request.resolved_params.get(key)
        effective_plugin_params["task_type"] = request.task_type
        effective_plugin_params["mode"] = request.mode

        try:
            metadata_plugin.validate_params(effective_plugin_params, context=runtime_context_candidate)
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.PLUGIN_RESOLUTION,
                default_code=TaskErrorCode.PARAM_VALIDATE_FAILED,
                exc=exc,
                message=(
                    f"插件参数校验失败 plugin_id={request.plugin_id} "
                    f"task_id={request.task_id}: {exc}"
                ),
            ) from exc

        requested_device = effective_plugin_params.get("device", "auto")
        profiles = self._resolve_runtime_profiles(metadata_plugin)
        try:
            selected_profile = self._profile_selector.select(
                profiles=profiles,
                host_capability=host_capability,
                requested_device=requested_device,
            )
        except Exception as exc:
            raise wrap_task_error(
                stage=TaskStage.PLUGIN_RESOLUTION,
                default_code=TaskErrorCode.PROFILE_UNSATISFIED,
                exc=exc,
                message=(
                    f"运行时配置选择失败 plugin_id={request.plugin_id} "
                    f"task_id={request.task_id}: {exc}"
                ),
            ) from exc

        return TaskExecutionPlan(
            request=request,
            metadata_plugin=metadata_plugin,
            host_capability=host_capability,
            runtime_context=runtime_context_candidate,
            effective_plugin_params=dict(effective_plugin_params),
            selected_profile=selected_profile,
        )

    @staticmethod
    def _resolved_config_to_dict(resolved_config: Any) -> dict[str, Any]:
        if hasattr(resolved_config, "to_dict") and callable(resolved_config.to_dict):
            payload = resolved_config.to_dict()
            return dict(payload) if isinstance(payload, dict) else {}
        if isinstance(resolved_config, dict):
            return dict(resolved_config)
        return {}

    @staticmethod
    def _resolve_runtime_profiles(metadata_plugin: Any) -> list[RuntimeProfileSpec]:
        runtime_profiles = getattr(metadata_plugin, "runtime_profiles", None)
        if isinstance(runtime_profiles, list):
            if all(isinstance(item, RuntimeProfileSpec) for item in runtime_profiles):
                return list(runtime_profiles)
            rows = [dict(item) for item in runtime_profiles if isinstance(item, Mapping)]
            if rows:
                return parse_runtime_profiles(rows)

        manifest = getattr(metadata_plugin, "manifest", None)
        raw = getattr(manifest, "runtime_profiles", []) if manifest is not None else []
        rows = [dict(item) for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []
        return parse_runtime_profiles(rows)

    @staticmethod
    def _build_runtime_context(request: TaskExecutionRequest) -> TaskRuntimeContext:
        def _safe_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except Exception:
                return default

        return TaskRuntimeContext(
            task_id=request.task_id,
            round_id=request.round_id,
            round_index=max(0, _safe_int(request.round_index, 0)),
            attempt=max(1, _safe_int(request.attempt, 1)),
            task_type=request.task_type,
            mode=request.mode,
            split_seed=max(0, _safe_int(request.resolved_params.get("split_seed"), 0)),
            train_seed=max(0, _safe_int(request.resolved_params.get("train_seed"), 0)),
            sampling_seed=max(0, _safe_int(request.resolved_params.get("sampling_seed"), 0)),
            resolved_device_backend="",
        )
