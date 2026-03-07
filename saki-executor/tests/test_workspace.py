from __future__ import annotations

from saki_executor.steps.workspace import Workspace


def test_workspace_resolves_relative_runs_dir_to_absolute(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    workspace = Workspace("runs", "task-1", round_id="round-1", attempt=2)

    assert workspace.runs_root == (tmp_path / "runs").resolve()
    assert workspace.root == (
        tmp_path
        / "runs"
        / "rounds"
        / "round-1"
        / "attempt_2"
        / "steps"
        / "task-1"
    ).resolve()
