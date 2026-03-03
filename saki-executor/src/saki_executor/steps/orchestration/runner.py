from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from saki_executor.core.config import settings
from saki_executor.agent import codec as runtime_codec
from saki_executor.plugins.venv_manager import ensure_plugin_venv_for_profile
from saki_executor.plugins.ipc.proxy_plugin import SubprocessPluginProxy
from saki_executor.runtime.binding.device_binding_resolver import DeviceBindingResolver
from saki_executor.runtime.capability.host_probe_service import HostProbeService
from saki_executor.runtime.profile.profile_selector import ProfileSelectorStrategy
from saki_executor.steps.contracts import SUPPORTED_LOOP_MODES, StepExecutionRequest, StepFinalResult
from saki_executor.steps.orchestration.event_emitter import StepEventEmitter
from saki_executor.steps.orchestration.training_data_service import TrainingDataService
from saki_executor.steps.state import ExecutorState, StepStatus
from saki_executor.steps.workspace import Workspace
from saki_executor.steps.workspace_adapter import WorkspaceAdapter
from saki_plugin_sdk import (
    ExecutionBindingContext,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    RuntimeProfileSpec,
    StepReporter,
    StepRuntimeRequirements,
    StepRuntimeContext,
    WorkspaceProtocol,
    parse_runtime_profiles,
)

if TYPE_CHECKING:
    from saki_executor.steps.manager import StepManager


@dataclass(frozen=True, slots=True)
class _InferenceTaskProfile:
    name: str
    query_type: str
    candidate_limit_mode: str
    default_strategy: str
    metric_key: str
    skip_when_strategy_empty: bool


class StepPipelineRunner:
    _SUPPORTED_MODES = SUPPORTED_LOOP_MODES
    _ORCHESTRATOR_ONLY_STEP_TYPES = {
        "select",
    }
    _TRAINING_PIPELINE_STEP_TYPES = {
        "train",
        "score",
        "eval",
        "predict",
        "custom",
    }
    _TRAIN_ONLY_STEP_TYPES = {
        "train",
    }
    _TRAIN_AND_SAMPLE_STEP_TYPES = {
        "custom",
    }
    _SCORE_ONLY_STEP_TYPES = {
        "score",
    }
    _EVAL_ONLY_STEP_TYPES = {
        "eval",
    }
    _PREDICT_ONLY_STEP_TYPES = {
        "predict",
    }

    def __init__(self, *, manager: StepManager, request: StepExecutionRequest) -> None:
        self._manager = manager
        self._request = request
        self._task_id = request.step_id
        self._effective_plugin_params: dict[str, Any] = {}
        self._runtime_context: StepRuntimeContext | None = None
        self._execution_binding_context: ExecutionBindingContext | None = None
        self._host_capability: HostCapabilitySnapshot | None = None
        self._runtime_capability: RuntimeCapabilitySnapshot | None = None
        self._selected_profile: RuntimeProfileSpec | None = None
        self._selected_worker_python: str | Path | None = None

    async def run(self) -> StepFinalResult:
        self._validate_request()
        metadata_plugin = self._resolve_plugin()
        workspace, reporter, emitter = self._prepare_workspace()
        await self._emit_dispatching_status(emitter)
        await self._prepare_profile_environment(metadata_plugin=metadata_plugin, emitter=emitter)
        plugin = self._build_execution_plugin(metadata_plugin=metadata_plugin, emitter=emitter)
        await self._prepare_execution_binding(plugin=plugin, emitter=emitter)
        await self._emit_running_status(emitter)
        runtime_requirements = plugin.get_step_runtime_requirements(self._request.step_type)
        await self._prepare_trained_model_if_needed(
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
        )

        metrics: dict[str, Any]
        artifacts: dict[str, Any]
        candidates: list[dict[str, Any]]
        optional_upload_failures: list[str]

        try:
            if self._request.step_type in (self._SCORE_ONLY_STEP_TYPES | self._PREDICT_ONLY_STEP_TYPES):
                inference_profile = self._inference_profile_for_step(self._request.step_type)
                metrics, artifacts, candidates, optional_upload_failures = await self._run_inference_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    runtime_requirements=runtime_requirements,
                    profile=inference_profile,
                )
            elif self._request.step_type in self._EVAL_ONLY_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_eval_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
                )
            elif self._request.step_type in self._TRAIN_ONLY_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_train_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
                )
            elif self._request.step_type in self._TRAIN_AND_SAMPLE_STEP_TYPES:
                metrics, artifacts, candidates, optional_upload_failures = await self._run_train_and_sample_pipeline(
                    plugin=plugin,
                    workspace=workspace,
                    emitter=emitter,
                    reporter=reporter,
                    runtime_requirements=runtime_requirements,
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
        self._host_capability = HostProbeService().probe(
            cpu_workers=settings.CPU_WORKERS,
            memory_mb=settings.MEMORY_MB,
        )
        raw_plugin_config = self._request.resolved_params.get("plugin")
        if not isinstance(raw_plugin_config, dict):
            raw_plugin_config = dict(self._request.resolved_params)
        runtime_context_candidate = self._build_runtime_context()
        try:
            plugin_config = plugin.resolve_config(
                self._request.mode,
                raw_plugin_config,
                context=runtime_context_candidate.to_dict(),
            )
        except Exception as exc:
            raise RuntimeError(
                f"plugin config resolve failed plugin_id={self._request.plugin_id} "
                f"step_id={self._request.step_id}: {exc}"
            ) from exc
        # Inject runtime seeds / round metadata – produce a plain dict for
        # IPC-serialisable downstream consumption.
        effective_plugin_params = plugin_config.to_dict()
        for key in ("split_seed", "train_seed", "sampling_seed", "round_index", "deterministic"):
            if key in self._request.resolved_params and key not in effective_plugin_params:
                effective_plugin_params[key] = self._request.resolved_params.get(key)
        effective_plugin_params["step_type"] = self._request.step_type
        effective_plugin_params["mode"] = self._request.mode
        runtime_context = runtime_context_candidate
        try:
            plugin.validate_params(effective_plugin_params, context=runtime_context)
        except Exception as exc:
            raise RuntimeError(
                f"plugin params validate failed plugin_id={self._request.plugin_id} "
                f"step_id={self._request.step_id}: {exc}"
            ) from exc
        requested_device = effective_plugin_params.get("device", "auto")
        profiles = self._resolve_runtime_profiles(plugin)
        selected_profile = ProfileSelectorStrategy().select(
            profiles=profiles,
            host_capability=self._host_capability,
            requested_device=requested_device,
        )
        self._selected_profile = selected_profile
        self._effective_plugin_params = effective_plugin_params
        self._runtime_context = runtime_context
        return plugin

    async def _prepare_profile_environment(
        self,
        *,
        metadata_plugin: Any,
        emitter: StepEventEmitter,
    ) -> None:
        selected_profile = self._selected_profile
        if selected_profile is None:
            raise RuntimeError("runtime profile is not selected")
        await emitter.emit_status(StepStatus.SYNCING_ENV, "syncing plugin runtime environment")
        self._selected_worker_python = self._resolve_worker_python(metadata_plugin, selected_profile)

    def _resolve_runtime_profiles(self, plugin: Any) -> list[RuntimeProfileSpec]:
        runtime_profiles = getattr(plugin, "runtime_profiles", None)
        if isinstance(runtime_profiles, list):
            rows = runtime_profiles
        else:
            manifest = getattr(plugin, "manifest", None)
            raw = getattr(manifest, "runtime_profiles", []) if manifest is not None else []
            rows = raw if isinstance(raw, list) else []
        return parse_runtime_profiles(rows)

    def _resolve_worker_python(
        self,
        plugin: Any,
        profile: RuntimeProfileSpec,
    ) -> str | Path | None:
        plugin_dir = getattr(plugin, "plugin_dir", None)
        if not plugin_dir:
            return getattr(plugin, "python_path", None)
        return ensure_plugin_venv_for_profile(
            plugin_dir=Path(str(plugin_dir)),
            plugin_id=str(getattr(plugin, "plugin_id", self._request.plugin_id) or self._request.plugin_id),
            plugin_version=str(getattr(plugin, "version", "0.0.0") or "0.0.0"),
            profile=profile,
            auto_sync=settings.PLUGIN_VENV_AUTO_SYNC,
        )

    def _build_runtime_context(
        self,
        *,
        resolved_device_backend: str | None = None,
    ) -> StepRuntimeContext:
        def _safe_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except Exception:
                return default

        return StepRuntimeContext(
            step_id=self._request.step_id,
            round_id=self._request.round_id,
            round_index=max(0, _safe_int(self._request.round_index, 0)),
            attempt=max(1, _safe_int(self._request.attempt, 1)),
            step_type=self._request.step_type,
            mode=self._request.mode,
            split_seed=max(0, _safe_int(self._request.resolved_params.get("split_seed"), 0)),
            train_seed=max(0, _safe_int(self._request.resolved_params.get("train_seed"), 0)),
            sampling_seed=max(0, _safe_int(self._request.resolved_params.get("sampling_seed"), 0)),
            resolved_device_backend=str(
                resolved_device_backend
                if resolved_device_backend is not None
                else (self._request.resolved_params.get("_resolved_device_backend") or "")
            ).strip().lower(),
        )

    def _require_runtime_context(self) -> StepRuntimeContext:
        if self._runtime_context is None:
            raise RuntimeError(f"runtime context is not initialized: {self._request.step_id}")
        return self._runtime_context

    def _require_execution_context(self) -> ExecutionBindingContext:
        if self._execution_binding_context is None:
            raise RuntimeError(f"execution binding context is not initialized: {self._request.step_id}")
        return self._execution_binding_context

    def _build_execution_plugin(self, *, metadata_plugin: Any, emitter: StepEventEmitter):
        # Extract external plugin info if available
        python_executable = self._selected_worker_python or getattr(metadata_plugin, "python_path", None)
        entrypoint_module = getattr(metadata_plugin, "entrypoint", None)
        if self._selected_profile and self._selected_profile.entrypoint:
            entrypoint_module = self._selected_profile.entrypoint
        extra_env = dict(self._selected_profile.env) if self._selected_profile else {}

        plugin = SubprocessPluginProxy(
            metadata_plugin=metadata_plugin,
            step_id=self._request.step_id,
            emit=emitter.emit,
            python_executable=python_executable,
            entrypoint_module=entrypoint_module,
            extra_env=extra_env,
        )
        self._manager._active_plugin = plugin  # noqa: SLF001
        return plugin

    async def _prepare_execution_binding(
        self,
        *,
        plugin: Any,
        emitter: StepEventEmitter,
    ) -> None:
        runtime_context = self._require_runtime_context()
        selected_profile = self._selected_profile
        host_capability = self._host_capability
        if selected_profile is None:
            raise RuntimeError("runtime profile is not selected")
        if host_capability is None:
            raise RuntimeError("host capability is not resolved")

        await emitter.emit_status(StepStatus.PROBING_RUNTIME, "probing plugin runtime capability")
        runtime_capability = await plugin.probe_runtime_capability(context=runtime_context)
        if not isinstance(runtime_capability, RuntimeCapabilitySnapshot):
            runtime_capability = RuntimeCapabilitySnapshot.from_dict(dict(runtime_capability or {}))

        await emitter.emit_status(StepStatus.BINDING_DEVICE, "binding execution device")
        binding = DeviceBindingResolver().resolve(
            requested_device=self._effective_plugin_params.get("device", "auto"),
            host_capability=host_capability,
            runtime_capability=runtime_capability,
            supported_backends=list(getattr(plugin, "supported_accelerators", []) or []),
            profile=selected_profile,
            allow_auto_fallback=bool(getattr(plugin, "supports_auto_fallback", True)),
        )
        self._effective_plugin_params["_resolved_device_backend"] = binding.backend
        self._effective_plugin_params["_resolved_device_spec"] = binding.device_spec
        execution_context = ExecutionBindingContext(
            step_context=self._require_runtime_context(),
            host_capability=host_capability,
            runtime_capability=runtime_capability,
            device_binding=binding,
            profile_id=selected_profile.id,
        )
        bind_context = getattr(plugin, "bind_execution_context", None)
        if callable(bind_context):
            await bind_context(execution_context)
        try:
            plugin.validate_params(self._effective_plugin_params, context=execution_context)
        except Exception as exc:
            raise RuntimeError(
                f"plugin params validate failed after binding plugin_id={self._request.plugin_id} "
                f"step_id={self._request.step_id}: {exc}"
            ) from exc
        self._execution_binding_context = execution_context
        self._runtime_capability = runtime_capability
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "execution binding resolved "
                    f"profile={selected_profile.id} backend={binding.backend} "
                    f"device_spec={binding.device_spec} fallback={binding.fallback_applied}"
                ),
            },
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    "execution capability snapshots "
                    f"host_capability={host_capability.to_dict()} "
                    f"runtime_capability={runtime_capability.to_dict()} "
                    f"selected_profile={selected_profile.to_dict()} "
                    f"device_binding={binding.to_dict()}"
                ),
            },
        )

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

    async def _run_training_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> tuple[Any, set[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
        )
        output = await plugin.train(
            workspace,
            self._effective_plugin_params,
            emitter.emit,
            context=self._require_execution_context(),
        )
        return output, protected

    async def _prepare_plugin_data(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
    ) -> set[str]:
        runtime_context = self._require_runtime_context()
        plugin_params_snapshot = {
            key: self._effective_plugin_params.get(key)
            for key in sorted(self._effective_plugin_params.keys())
            if not str(key).startswith("_")
        }
        params_snapshot = {
            "split_seed": runtime_context.split_seed,
            "train_seed": runtime_context.train_seed,
            "sampling_seed": runtime_context.sampling_seed,
            "mode": runtime_context.mode,
            "step_type": runtime_context.step_type,
            "round_index": runtime_context.round_index,
            "step_id": runtime_context.step_id,
            "plugin_params": plugin_params_snapshot,
        }
        await emitter.emit("log", {"level": "INFO", "message": f"effective training params: {params_snapshot}"})
        data_service = TrainingDataService(
            fetch_all=self._manager._fetch_all,  # noqa: SLF001
            cache=self._manager.cache,
            stop_event=self._manager._stop_event,  # noqa: SLF001
        )
        data_bundle = await data_service.prepare(
            request=self._request,
            plugin_params=self._effective_plugin_params,
            runtime_context=runtime_context,
            emit=emitter.emit,
        )
        await plugin.prepare_data(
            workspace=workspace,
            labels=data_bundle.labels,
            samples=data_bundle.samples,
            annotations=data_bundle.train_annotations,
            dataset_ir=data_bundle.ir_batch,
            splits=dict(data_bundle.splits),
            context=self._require_execution_context(),
        )
        return data_bundle.protected

    async def _prepare_data_for_step(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> set[str]:
        if not runtime_requirements.requires_prepare_data:
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"prepare_data skipped by runtime requirements "
                        f"step_type={self._request.step_type}"
                    ),
                },
            )
            return set()

        fingerprint = self._build_data_cache_fingerprint()
        can_use_shared_cache = (
            self._manager.round_shared_cache_enabled
            and self._request.round_id
            and self._request.step_type != "train"
        )
        if can_use_shared_cache:
            try:
                if workspace.restore_shared_data_cache(fingerprint):
                    await emitter.emit(
                        "log",
                        {
                            "level": "INFO",
                            "message": (
                                f"round shared data cache hit "
                                f"fingerprint={fingerprint}"
                            ),
                        },
                    )
                    return set()
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": (
                            f"round shared data cache restore failed "
                            f"fingerprint={fingerprint} error={exc}"
                        ),
                    },
                )

        protected = await self._prepare_plugin_data(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
        )
        if self._manager.round_shared_cache_enabled and self._request.round_id:
            try:
                cached_path = workspace.store_shared_data_cache(
                    fingerprint=fingerprint,
                    source_step_id=self._request.step_id,
                    step_type=self._request.step_type,
                )
                await emitter.emit(
                    "log",
                    {
                        "level": "INFO",
                        "message": (
                            f"round shared data cache stored "
                            f"fingerprint={fingerprint} path={cached_path}"
                        ),
                    },
                )
            except Exception as exc:
                await emitter.emit(
                    "log",
                    {
                        "level": "WARN",
                        "message": (
                            f"round shared data cache store failed "
                            f"fingerprint={fingerprint} error={exc}"
                        ),
                    },
                )
        return protected

    def _build_data_cache_fingerprint(self) -> str:
        runtime_context = self._require_runtime_context()
        plugin_subset = {
            key: self._effective_plugin_params.get(key)
            for key in sorted(self._effective_plugin_params.keys())
            if not str(key).startswith("_")
        }
        payload = {
            "version": 1,
            "round_id": self._request.round_id,
            "attempt": self._request.attempt,
            "project_id": self._request.project_id,
            "input_commit_id": self._request.input_commit_id,
            "plugin_id": self._request.plugin_id,
            "mode": runtime_context.mode,
            "split_seed": runtime_context.split_seed,
            "plugin_subset": plugin_subset,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _prepare_trained_model_if_needed(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> None:
        if not runtime_requirements.requires_trained_model:
            return

        artifact_name = str(runtime_requirements.primary_model_artifact_name or "best.pt").strip() or "best.pt"
        linked = workspace.link_shared_model_to_step(artifact_name)
        if linked is not None and linked.exists():
            # Keep plugin-side model resolution deterministic: if shared model is available,
            # pin model_source/model_custom_ref to the local shared path.
            self._effective_plugin_params["model_source"] = "custom_local"
            self._effective_plugin_params["model_custom_ref"] = str(linked)
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"trained model resolved source=shared "
                        f"artifact={artifact_name} path={linked}"
                    ),
                },
            )
            return

        model_source = str(self._effective_plugin_params.get("model_source") or "").strip().lower()
        model_ref = str(self._effective_plugin_params.get("model_custom_ref") or "").strip()
        if model_source in {"custom_url", "custom_local"} and model_ref:
            await emitter.emit(
                "log",
                {
                    "level": "INFO",
                    "message": (
                        f"trained model resolved source=remote "
                        f"artifact={artifact_name} model_source={model_source}"
                    ),
                },
            )
            return

        message = (
            f"trained model is required but unavailable: "
            f"artifact={artifact_name} step_type={self._request.step_type}"
        )
        if self._manager.strict_train_model_handoff:
            raise RuntimeError(message)
        await emitter.emit(
            "log",
            {
                "level": "WARN",
                "message": f"{message}; STRICT_TRAIN_MODEL_HANDOFF=false fallback enabled",
            },
        )

    async def _cache_primary_model_after_train(
        self,
        *,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        runtime_requirements: StepRuntimeRequirements,
        output_artifacts: list[Any],
    ) -> None:
        if not self._manager.round_shared_cache_enabled or not self._request.round_id:
            return

        artifact_name = str(runtime_requirements.primary_model_artifact_name or "best.pt").strip() or "best.pt"
        primary_artifact = next(
            (item for item in output_artifacts if str(getattr(item, "name", "")).strip() == artifact_name),
            None,
        )
        if primary_artifact is None:
            await emitter.emit(
                "log",
                {
                    "level": "WARN",
                    "message": (
                        f"round shared model cache skip: primary artifact not found "
                        f"artifact={artifact_name}"
                    ),
                },
            )
            return

        source_path = Path(primary_artifact.path)
        if not source_path.exists():
            await emitter.emit(
                "log",
                {
                    "level": "WARN",
                    "message": (
                        f"round shared model cache skip: artifact file missing "
                        f"artifact={artifact_name} path={source_path}"
                    ),
                },
            )
            return

        cached_path = workspace.cache_model_artifact(
            artifact_name=artifact_name,
            source_path=source_path,
            source_step_id=self._request.step_id,
        )
        await emitter.emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"round shared model cache stored "
                    f"artifact={artifact_name} path={cached_path}"
                ),
            },
        )

    async def _run_train_and_sample_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        reporter: StepReporter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        output, protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
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

    async def _run_train_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        reporter: StepReporter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        output, _protected = await self._run_training_pipeline(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
        )
        await self._cache_primary_model_after_train(
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
            output_artifacts=output.artifacts,
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, [], optional_upload_failures

    async def _run_eval_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        reporter: StepReporter,
        runtime_requirements: StepRuntimeRequirements,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
        )
        output = await plugin.eval(
            workspace,
            self._effective_plugin_params,
            emitter.emit,
            context=self._require_execution_context(),
        )
        artifacts, optional_upload_failures = await self._upload_artifacts(
            output_artifacts=output.artifacts,
            reporter=reporter,
        )
        return output.metrics, artifacts, [], optional_upload_failures

    @staticmethod
    def _inference_profile_for_step(step_type: str) -> _InferenceTaskProfile:
        normalized = str(step_type or "").strip().lower()
        if normalized == "predict":
            return _InferenceTaskProfile(
                name="predict",
                query_type="samples",
                candidate_limit_mode="keep_all",
                default_strategy="uncertainty_1_minus_max_conf",
                metric_key="predict_candidate_count",
                skip_when_strategy_empty=False,
            )
        return _InferenceTaskProfile(
            name="score",
            query_type="unlabeled_samples",
            candidate_limit_mode="review_pool",
            default_strategy="",
            metric_key="score_candidate_count",
            skip_when_strategy_empty=True,
        )

    async def _run_inference_pipeline(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        runtime_requirements: StepRuntimeRequirements,
        profile: _InferenceTaskProfile,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
        protected = await self._prepare_data_for_step(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            runtime_requirements=runtime_requirements,
        )
        candidates = await self._collect_candidates(
            plugin=plugin,
            workspace=workspace,
            emitter=emitter,
            protected=protected,
            profile=profile,
        )
        metrics: dict[str, Any] = {
            profile.metric_key: float(len(candidates)),
        }
        return metrics, {}, candidates, []

    async def _collect_candidates(
        self,
        *,
        plugin: Any,
        workspace: WorkspaceProtocol,
        emitter: StepEventEmitter,
        protected: set[str],
        profile: _InferenceTaskProfile | None = None,
    ) -> list[dict[str, Any]]:
        mode = self._request.mode
        query_type = "unlabeled_samples"
        candidate_limit_mode = "topk"
        default_strategy = ""
        skip_when_strategy_empty = True
        if profile is not None:
            query_type = profile.query_type
            candidate_limit_mode = profile.candidate_limit_mode
            default_strategy = profile.default_strategy
            skip_when_strategy_empty = profile.skip_when_strategy_empty

        is_keep_all = candidate_limit_mode == "keep_all"
        skip_sampling = bool(self._request.resolved_params.get("skip_sampling", False))
        if mode == "manual" and not is_keep_all:
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
            or default_strategy
        ).strip()
        if not strategy:
            if skip_when_strategy_empty:
                await emitter.emit("log", {"level": "INFO", "message": "sampling strategy is empty, skip sampling"})
                return []
            strategy = "uncertainty_1_minus_max_conf"
        topk = int(sampling_cfg.get("topk", self._request.resolved_params.get("topk", 200)))
        review_pool_size = int(sampling_cfg.get("review_pool_size", 0) or 0)
        if review_pool_size <= 0:
            review_pool_multiplier = int(sampling_cfg.get("review_pool_multiplier", 3) or 3)
            review_pool_multiplier = max(1, review_pool_multiplier)
            review_pool_size = max(topk, topk * review_pool_multiplier)
        if candidate_limit_mode == "keep_all":
            candidate_limit = 0
        elif candidate_limit_mode == "review_pool":
            candidate_limit = max(topk, review_pool_size)
        else:
            candidate_limit = topk
        sampling_params = dict(self._effective_plugin_params)
        sampling_params.update(sampling_cfg)
        sampling_params["sampling_topk"] = candidate_limit
        runtime_context = self._require_runtime_context()
        sampling_params["sampling_seed"] = int(
            sampling_params.get("sampling_seed", runtime_context.sampling_seed)
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
            query_type=query_type,
            topk=candidate_limit,
            context=self._require_execution_context(),
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
