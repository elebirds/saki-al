from __future__ import annotations

from pathlib import Path

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


def test_workspace_store_and_restore_prepared_data_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "executor-cache" / "prepared_data_v2"
    writer = Workspace(
        str(tmp_path / "runs"),
        "task-writer",
        round_id="round-1",
        attempt=1,
        prepared_data_cache_root=cache_root,
    )
    writer.ensure()
    (writer.data_dir / "images").mkdir(parents=True, exist_ok=True)
    (writer.data_dir / "images" / "sample-1.jpg").write_bytes(b"image")
    (writer.data_dir / "dataset.yaml").write_text("train: images/train\n", encoding="utf-8")

    cached_path = writer.store_prepared_data_cache("fp-1", "task-writer")

    reader = Workspace(
        str(tmp_path / "runs"),
        "task-reader",
        round_id="round-2",
        attempt=3,
        prepared_data_cache_root=cache_root,
    )
    reader.ensure()
    (reader.data_dir / "stale.txt").write_text("stale", encoding="utf-8")

    assert reader.restore_prepared_data_cache("fp-1") is True
    assert cached_path == cache_root / "fp-1"
    assert (reader.data_dir / "images" / "sample-1.jpg").read_bytes() == b"image"
    assert (reader.data_dir / "dataset.yaml").read_text(encoding="utf-8") == "train: images/train\n"
    assert not (reader.data_dir / "stale.txt").exists()
