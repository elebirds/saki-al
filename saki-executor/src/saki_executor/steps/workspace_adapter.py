from __future__ import annotations

from pathlib import Path
from typing import Any

from saki_executor.steps.workspace import Workspace as ExecutorWorkspace
from saki_plugin_sdk.workspace_protocol import WorkspaceProtocol


class WorkspaceAdapter(WorkspaceProtocol):
    """Adapter that exposes executor workspace via SDK workspace protocol."""

    def __init__(self, workspace: ExecutorWorkspace) -> None:
        self._workspace = workspace

    @property
    def raw(self) -> ExecutorWorkspace:
        return self._workspace

    @property
    def task_id(self) -> str:
        return self._workspace.task_id

    @property
    def root(self) -> Path:
        return self._workspace.root

    @property
    def config_path(self) -> Path:
        return self._workspace.config_path

    @property
    def events_path(self) -> Path:
        return self._workspace.events_path

    @property
    def artifacts_dir(self) -> Path:
        return self._workspace.artifacts_dir

    @property
    def data_dir(self) -> Path:
        return self._workspace.data_dir

    @property
    def cache_dir(self) -> Path:
        return self._workspace.cache_dir

    def ensure(self) -> None:
        self._workspace.ensure()

    def write_config(self, payload: dict[str, Any]) -> None:
        self._workspace.write_config(payload)

    def restore_shared_data_cache(self, fingerprint: str) -> bool:
        return self._workspace.restore_shared_data_cache(fingerprint)

    def store_shared_data_cache(self, fingerprint: str, source_task_id: str, task_type: str) -> Path:
        return self._workspace.store_shared_data_cache(fingerprint, source_task_id, task_type)

    def link_shared_model_to_step(self, artifact_name: str) -> Path | None:
        return self._workspace.link_shared_model_to_step(artifact_name)

    def cache_model_artifact(self, artifact_name: str, source_path: Path, source_task_id: str) -> Path:
        return self._workspace.cache_model_artifact(artifact_name, source_path, source_task_id)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._workspace, item)
