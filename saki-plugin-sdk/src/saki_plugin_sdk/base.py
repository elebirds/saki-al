"""Base classes for Saki plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from saki_plugin_sdk.workspace import Workspace


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
        """Initialize the plugin with logger and step_id tracking."""
        self._logger: Any | None = None
        self._step_id: str | None = None
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
        return self._manifest

    # -------------------------------------------------------------------
    # Metadata properties (auto-loaded from manifest if available)
    # -------------------------------------------------------------------

    @property
    def plugin_id(self) -> str:
        """Unique plugin identifier (e.g. ``\"yolo_det_v1\"``).

        Default implementation reads from manifest. Subclasses may override
        if they need to compute this dynamically.
        """
        if self._manifest:
            return self._manifest.plugin_id
        raise NotImplementedError(
            "plugin_id not implemented. Either set self._manifest in __init__() "
            "by calling self._load_manifest(), or override this property."
        )

    @property
    def version(self) -> str:
        """Plugin version string (e.g. ``\"0.2.0\"``).

        Default implementation reads from manifest.
        """
        if self._manifest:
            return self._manifest.version
        return "0.0.0"

    @property
    def display_name(self) -> str:
        """Human-readable display name.

        Default implementation reads from manifest, falling back to plugin_id.
        """
        if self._manifest and self._manifest.display_name:
            return self._manifest.display_name
        return self.plugin_id

    @property
    def supported_step_types(self) -> list[str]:
        """List of supported step types.

        Default implementation reads from manifest.
        """
        if self._manifest:
            return self._manifest.supported_step_types
        return []

    @property
    def supported_strategies(self) -> list[str]:
        """List of supported sampling strategies.

        Default implementation reads from manifest.
        """
        if self._manifest:
            return self._manifest.supported_strategies
        return []

    @property
    def supported_accelerators(self) -> list[str]:
        """List of supported accelerator types.

        Default implementation reads from manifest, falling back to [\"cpu\"].
        """
        if self._manifest:
            return self._manifest.supported_accelerators
        return ["cpu"]

    @property
    def supports_auto_fallback(self) -> bool:
        """Whether automatic CPU fallback is supported.

        Default implementation reads from manifest, falling back to True.
        """
        if self._manifest:
            return self._manifest.supports_auto_fallback
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

    async def on_start(self, step_id: str, workspace: Workspace) -> None:
        """Called before step execution begins.

        Override to initialize step-specific resources.
        The default implementation updates step_id tracking.

        Parameters
        ----------
        step_id : str
            The step identifier.
        workspace : Workspace
            The step workspace directory.
        """
        self._step_id = step_id
        if self._logger and hasattr(self._logger, "step_id"):
            self._logger.step_id = step_id

    async def on_stop(self, step_id: str, workspace: Workspace) -> None:
        """Called after step execution completes (success or failure).

        Override to cleanup step-specific resources.
        The default implementation does nothing.

        Parameters
        ----------
        step_id : str
            The step identifier.
        workspace : Workspace
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
        ``plugin_id`` and current ``step_id`` as context prefix.
        """
        if self._logger is None:
            from saki_plugin_sdk.logger import PluginLogger
            self._logger = PluginLogger(
                plugin_id=self.plugin_id,
                step_id=self._step_id,
            )
        return self._logger

    # -------------------------------------------------------------------
    # Abstract execution methods
    # -------------------------------------------------------------------

    @abstractmethod
    async def train(
            self,
            workspace: Workspace,
            params: dict[str, Any],
            emit: EventCallback,
    ) -> TrainOutput:
        """Execute training step.

        Parameters
        ----------
        workspace : Workspace
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
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run prediction on unlabeled samples.

        Parameters
        ----------
        workspace : Workspace
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

    async def prepare_data(
            self,
            workspace: Workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir: Any,
            splits: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        """Prepare training data (optional override).

        The default implementation does nothing.
        """
        del workspace, labels, samples, annotations, dataset_ir, splits

    async def predict_unlabeled_batch(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Batch prediction (delegates to ``predict_unlabeled`` by default)."""
        return await self.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
        )

    async def stop(self, step_id: str) -> None:
        """Request graceful stop (optional override).

        The default implementation does nothing.
        """
        del step_id
