from __future__ import annotations

from saki_plugin_sdk import Workspace, WorkspaceProtocol


def test_sdk_workspace_satisfies_workspace_protocol(tmp_path):
    workspace = Workspace(str(tmp_path / "runs"), "step-workspace-protocol")
    workspace.ensure()
    assert isinstance(workspace, WorkspaceProtocol)
    assert workspace.task_id == "step-workspace-protocol"
    assert workspace.root.exists()
    assert workspace.artifacts_dir.exists()
    assert workspace.data_dir.exists()
    assert workspace.cache_dir.exists()
