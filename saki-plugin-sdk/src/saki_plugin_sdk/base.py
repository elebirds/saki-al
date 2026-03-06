"""Base classes for Saki plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from saki_plugin_sdk.capability_types import RuntimeCapabilitySnapshot
from saki_plugin_sdk.execution_binding_context import ExecutionBindingContext
from saki_plugin_sdk.types import TaskRuntimeContext
from saki_plugin_sdk.workspace_protocol import WorkspaceProtocol


EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class TrainArtifact:
    kind: str
    name: str
    path: Path
    content_type: str = "application/octet-stream"
    meta: dict[str, Any] | None = None
    required: bool = False


@dataclass
class TrainOutput:
    metrics: dict[str, Any]
    artifacts: list[TrainArtifact]


@dataclass(frozen=True)
class TaskRuntimeRequirements:
    requires_prepare_data: bool
    requires_trained_model: bool
    primary_model_artifact_name: str = "best.pt"


def default_task_runtime_requirements(task_type: str) -> TaskRuntimeRequirements:
    normalized = str(task_type or "").strip().lower()
    if normalized == "train":
        return TaskRuntimeRequirements(
            requires_prepare_data=True,
            requires_trained_model=False,
            primary_model_artifact_name="best.pt",
        )
    if normalized == "score":
        return TaskRuntimeRequirements(
            requires_prepare_data=False,
            requires_trained_model=True,
            primary_model_artifact_name="best.pt",
        )
    if normalized == "eval":
        return TaskRuntimeRequirements(
            requires_prepare_data=True,
            requires_trained_model=True,
            primary_model_artifact_name="best.pt",
        )
    if normalized == "predict":
        return TaskRuntimeRequirements(
            requires_prepare_data=False,
            requires_trained_model=True,
            primary_model_artifact_name="best.pt",
        )
    if normalized == "custom":
        return TaskRuntimeRequirements(
            requires_prepare_data=True,
            requires_trained_model=False,
            primary_model_artifact_name="best.pt",
        )
    return TaskRuntimeRequirements(
        requires_prepare_data=True,
        requires_trained_model=False,
        primary_model_artifact_name="best.pt",
    )


def resolve_task_runtime_requirements(
    task_type: str,
    requirements_map: Mapping[str, Any] | None = None,
) -> TaskRuntimeRequirements:
    default = default_task_runtime_requirements(task_type)
    if not isinstance(requirements_map, Mapping):
        return default

    normalized = str(task_type or "").strip().lower()
    raw = requirements_map.get(normalized)
    if raw is None:
        raw = requirements_map.get(task_type)
    if not isinstance(raw, Mapping):
        return default

    artifact_name = str(
        raw.get("primary_model_artifact_name", default.primary_model_artifact_name)
        or default.primary_model_artifact_name
    ).strip()
    return TaskRuntimeRequirements(
        requires_prepare_data=bool(raw.get("requires_prepare_data", default.requires_prepare_data)),
        requires_trained_model=bool(raw.get("requires_trained_model", default.requires_trained_model)),
        primary_model_artifact_name=artifact_name,
    )


class ExecutorPlugin(ABC):
    """Base class that every Saki plugin must implement.

    Simplified design:
    - Most metadata properties (plugin_id, version, etc.) are automatically
      loaded from plugin.yml via the manifest property
    - Subclasses only need to implement train() and predict_unlabeled()
    - All other methods have sensible defaults or are optional hooks

    To create a minimal plugin::

        from saki_plugin_sdk import ExecutorPlugin

        class MyPlugin(ExecutorPlugin):
            def __init__(self):
                super().__init__()
                self._manifest = self._load_manifest()

            async def train(self, workspace, params, emit):
                # Training logic here
                pass
    """

    def __init__(self) -> None:
        """Initialize the plugin with logger and task_id tracking."""
        self._logger: Any | None = None
        self._task_id: str | None = None
        self._manifest: Any | None = None

    def _load_manifest(self) -> Any:
        """Load PluginManifest from plugin.yml.

        This is a convenience method for subclasses to call in __init__.
        The manifest is used to provide default implementations for
        metadata properties.

        Note: This default implementation looks for plugin.yml in
        standard locations relative to the plugin module.
        """
        from saki_plugin_sdk.manifest import PluginManifest

        # Find plugin.yml relative to the calling plugin's __file__
        # Get the caller's frame to find the plugin module path
        import inspect
        caller_frame = inspect.currentframe().f_back
        if caller_frame:
            caller_file = Path(caller_frame.f_code.co_filename).resolve()
        else:
            caller_file = Path(__file__).resolve()

        # Try standard plugin.yml locations
        candidates = [
            caller_file.parent.parent / "plugin.yml",  # src/my_plugin/plugin.yml
            caller_file.parent.parent.parent / "plugin.yml",  # monorepo layout
            caller_file.parent / "plugin.yml",  # plugin.yml next to __init__.py
        ]

        for plugin_yml in candidates:
            if plugin_yml.exists():
                return PluginManifest.from_yaml(plugin_yml)

        raise FileNotFoundError(
            f"Could not find plugin.yml. Searched: {[str(p) for p in candidates]}"
        )

    @property
    def manifest(self) -> Any:
        """Get the plugin manifest (plugin.yml metadata).

        Subclasses should set self._manifest in __init__() by calling
        self._load_manifest() or loading their own manifest.

        Returns:
            PluginManifest instance or None if not loaded
        """
        return getattr(self, "_manifest", None)

    # -------------------------------------------------------------------
    # Metadata properties (auto-loaded from manifest if available)
    # -------------------------------------------------------------------

    @property
    def plugin_id(self) -> str:
        """Unique plugin identifier (e.g. ``\"yolo_det_v1\"``).

        Default implementation reads from manifest. Subclasses may override
        if they need to compute this dynamically.
        """
        manifest = self.manifest
        if manifest:
            return manifest.plugin_id
        raise NotImplementedError(
            "plugin_id not implemented. Either set self._manifest in __init__() "
            "by calling self._load_manifest(), or override this property."
        )

    @property
    def version(self) -> str:
        """Plugin version string (e.g. ``\"0.2.0\"``).

        Default implementation reads from manifest.
        """
        manifest = self.manifest
        if manifest:
            return manifest.version
        return "0.0.0"

    @property
    def display_name(self) -> str:
        """Human-readable display name.

        Default implementation reads from manifest, falling back to plugin_id.
        """
        manifest = self.manifest
        if manifest and manifest.display_name:
            return manifest.display_name
        return self.plugin_id

    @property
    def supported_task_types(self) -> list[str]:
        """List of supported task types.

        Default implementation reads from manifest.
        """
        manifest = self.manifest
        if manifest:
            return manifest.supported_task_types
        return []

    @property
    def supported_strategies(self) -> list[str]:
        """List of supported sampling strategies.

        Default implementation reads from manifest.
        """
        manifest = self.manifest
        if manifest:
            return manifest.supported_strategies
        return []

    @property
    def request_config_schema(self) -> dict[str, Any]:
        manifest = self.manifest
        if manifest and isinstance(getattr(manifest, "config_schema", None), dict):
            return dict(manifest.config_schema)
        return {}

    @property
    def default_request_config(self) -> dict[str, Any]:
        manifest = self.manifest
        if manifest and isinstance(getattr(manifest, "default_config", None), dict):
            return dict(manifest.default_config)
        return {}

    def resolve_config(
        self,
        mode: str,
        raw_config: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> "PluginConfig":
        del mode
        from saki_plugin_sdk.config import ConfigSchema, PluginConfig

        return PluginConfig.resolve(
            schema=ConfigSchema.model_validate(self.request_config_schema or {}),
            raw_config=raw_config,
            context=context,
            validate=validate,
        )

    @property
    def supported_accelerators(self) -> list[str]:
        """List of supported accelerator types.

        Default implementation reads from manifest, falling back to [\"cpu\"].
        """
        manifest = self.manifest
        if manifest:
            return manifest.supported_accelerators
        return ["cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        """Whether automatic CPU fallback is supported.

        Default implementation reads from manifest, falling back to True.
        """
        manifest = self.manifest
        if manifest:
            return manifest.supports_auto_fallback
        return True

    # -------------------------------------------------------------------
    # Lifecycle hooks (optional, override as needed)
    # -------------------------------------------------------------------

    async def on_load(self, context: dict[str, Any]) -> None:
        """Called when the plugin is loaded (worker process startup).

        Override to initialize resources that persist across steps.
        The default implementation does nothing.

        Parameters
        ----------
        context : dict[str, Any]
            Execution context (may contain plugin_dir, executor_id, etc.).
        """
        pass

    async def on_start(self, task_id: str, workspace: WorkspaceProtocol) -> None:
        """Called before task execution begins.

        Override to initialize step-specific resources.
        The default implementation updates task_id tracking.

        Parameters
        ----------
        task_id : str
            The step identifier.
        workspace : WorkspaceProtocol
            The step workspace directory.
        """
        setattr(self, "_task_id", task_id)
        logger = getattr(self, "_logger", None)
        if logger and hasattr(logger, "task_id"):
            logger.task_id = task_id

    async def on_stop(self, task_id: str, workspace: WorkspaceProtocol) -> None:
        """Called after task execution completes (success or failure).

        Override to cleanup step-specific resources.
        The default implementation does nothing.

        Parameters
        ----------
        task_id : str
            The step identifier.
        workspace : WorkspaceProtocol
            The step workspace directory.
        """
        pass

    async def on_unload(self) -> None:
        """Called when the plugin is unloaded (worker process shutdown).

        Override to cleanup persistent resources.
        The default implementation does nothing.
        """
        pass

    # -------------------------------------------------------------------
    # Logger property (lazy initialization)
    # -------------------------------------------------------------------

    @property
    def logger(self) -> Any:
        """Get or create the plugin logger.

        Returns a :class:`PluginLogger` instance with the plugin's
        ``plugin_id`` and current ``task_id`` as context prefix.
        """
        logger = getattr(self, "_logger", None)
        if logger is None:
            from saki_plugin_sdk.logger import PluginLogger
            logger = PluginLogger(
                plugin_id=self.plugin_id,
                task_id=getattr(self, "_task_id", None),
            )
            setattr(self, "_logger", logger)
        return logger

    # -------------------------------------------------------------------
    # Abstract execution methods
    # -------------------------------------------------------------------

    @abstractmethod
    async def train(
            self,
            workspace: WorkspaceProtocol,
            params: dict[str, Any],
            emit: EventCallback,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        """Execute training step.

        Parameters
        ----------
        workspace : WorkspaceProtocol
            Step workspace directory.
        params : dict[str, Any]
            Resolved configuration parameters.
        emit : EventCallback
            Callback for emitting events (progress, metrics, etc.).

        Returns
        -------
        TrainOutput
            Training metrics and artifacts.
        """
        pass

    @abstractmethod
    async def predict_unlabeled(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        """Run prediction on unlabeled samples.

        Parameters
        ----------
        workspace : WorkspaceProtocol
            Step workspace directory.
        unlabeled_samples : list[dict[str, Any]]
            Samples to predict.
        strategy : str
            Sampling strategy name.
        params : dict[str, Any]
            Resolved configuration parameters.

        Returns
        -------
        list[dict[str, Any]]
            Prediction results with scores.
        """
        pass

    # -------------------------------------------------------------------
    # Optional execution methods (with default implementations)
    # -------------------------------------------------------------------

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: TaskRuntimeContext | ExecutionBindingContext | None = None,
    ) -> None:
        context_payload = context.to_dict() if hasattr(context, "to_dict") and context else None
        self.resolve_config(
            mode=str(params.get("mode") or "manual"),
            raw_config=params,
            context=context_payload,
            validate=True,
        )

    async def probe_runtime_capability(
        self,
        *,
        context: TaskRuntimeContext,
    ) -> RuntimeCapabilitySnapshot:
        del context
        return RuntimeCapabilitySnapshot.empty(framework="")

    def get_task_runtime_requirements(self, task_type: str) -> TaskRuntimeRequirements:
        manifest = self.manifest
        requirements_map = getattr(manifest, "task_runtime_requirements", {}) if manifest is not None else {}
        return resolve_task_runtime_requirements(task_type, requirements_map)

    async def prepare_data(
            self,
            workspace: WorkspaceProtocol,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: ExecutionBindingContext,
    ) -> None:
        """Prepare training data (optional override).

        The default implementation does nothing.
        """
        del workspace, labels, samples, annotations, dataset_ir, splits, context

    async def predict_unlabeled_batch(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        """Batch prediction (delegates to ``predict_unlabeled`` by default)."""
        return await self.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def eval(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        """Execute evaluation step.

        Plugins that declare ``eval`` in ``supported_task_types`` should override.
        """
        del workspace, params, emit, context
        raise NotImplementedError("eval step is not implemented by this plugin")

    async def predict(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        """Execute predict step.

        Plugins that declare ``predict`` in ``supported_task_types`` should override.
        """
        del workspace, params, emit, context
        raise NotImplementedError("predict step is not implemented by this plugin")

    async def stop(self, task_id: str) -> None:
        """Request graceful stop (optional override).

        The default implementation does nothing.
        """
        del task_id
