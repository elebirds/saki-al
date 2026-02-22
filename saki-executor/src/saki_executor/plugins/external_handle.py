"""Handle representing an externally-discovered plugin.

``ExternalPluginHandle`` implements the same ``ExecutorPlugin`` ABC
that the old built-in plugins did, but delegates metadata from the
``plugin.yml`` manifest and does **not** import any heavy plugin code.

The executor uses this handle purely for metadata / validation;
actual training/prediction runs through the IPC subprocess proxy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from saki_plugin_sdk.manifest import PluginManifest
from saki_executor.plugins.base import EventCallback, ExecutorPlugin, TrainOutput
from saki_executor.steps.workspace import Workspace


class ExternalPluginHandle(ExecutorPlugin):
    """Thin metadata wrapper around a plugin.yml manifest."""

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        plugin_dir: Path,
        python_path: Path,
    ) -> None:
        self._manifest = manifest
        self._plugin_dir = plugin_dir
        self._python_path = python_path

    # ------------------------------------------------------------------
    # Metadata properties (from manifest)
    # ------------------------------------------------------------------

    @property
    def plugin_id(self) -> str:
        return self._manifest.plugin_id

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def display_name(self) -> str:
        return self._manifest.display_name

    @property
    def supported_step_types(self) -> list[str]:
        return list(self._manifest.supported_step_types)

    @property
    def supported_strategies(self) -> list[str]:
        return list(self._manifest.supported_strategies)

    @property
    def supported_accelerators(self) -> list[str]:
        return list(self._manifest.supported_accelerators)

    @property
    def supports_auto_fallback(self) -> bool:
        return self._manifest.supports_auto_fallback

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return dict(self._manifest.config_schema) if self._manifest.config_schema else {}

    @property
    def default_request_config(self) -> dict[str, Any]:
        return dict(self._manifest.default_config) if self._manifest.default_config else {}

    # ------------------------------------------------------------------
    # Plugin directory / env helpers (used by IPC layer)
    # ------------------------------------------------------------------

    @property
    def plugin_dir(self) -> Path:
        return self._plugin_dir

    @property
    def python_path(self) -> Path:
        return self._python_path

    @property
    def entrypoint(self) -> str:
        return self._manifest.entrypoint

    def validate_params(self, params: dict[str, Any]) -> None:
        # Lightweight host-side validation; full validation happens in worker.
        pass

    # ------------------------------------------------------------------
    # Execution stubs — these should never be called directly.
    # All execution goes through SubprocessPluginProxy.
    # ------------------------------------------------------------------

    async def prepare_data(self, workspace: Workspace, labels, samples, annotations, dataset_ir, splits=None):
        raise RuntimeError("ExternalPluginHandle.prepare_data must not be called directly; use SubprocessPluginProxy")

    async def train(self, workspace: Workspace, params: dict[str, Any], emit: EventCallback) -> TrainOutput:
        raise RuntimeError("ExternalPluginHandle.train must not be called directly; use SubprocessPluginProxy")

    async def predict_unlabeled(self, workspace, unlabeled_samples, strategy, params):
        raise RuntimeError("ExternalPluginHandle.predict_unlabeled must not be called directly")

    async def predict_unlabeled_batch(self, workspace, unlabeled_samples, strategy, params):
        raise RuntimeError("ExternalPluginHandle.predict_unlabeled_batch must not be called directly")

    async def stop(self, step_id: str) -> None:
        pass
