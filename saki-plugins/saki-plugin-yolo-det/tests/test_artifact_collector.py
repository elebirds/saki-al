from __future__ import annotations

import os
from pathlib import Path

from saki_plugin_sdk.workspace import Workspace
from saki_plugin_yolo_det.artifact_collector import collect_optional_artifacts, resolve_save_dir


class _DummyTrainOutput:
    def __init__(self, save_dir: str) -> None:
        self.save_dir = save_dir


class _DummyModel:
    trainer = None


def test_resolve_save_dir_returns_absolute_path(tmp_path: Path):
    rel_save_dir = tmp_path / "runs" / "rounds" / "step-1" / "yolo_train"
    rel_save_dir.mkdir(parents=True, exist_ok=True)
    output = _DummyTrainOutput(str(rel_save_dir.relative_to(tmp_path)))

    current = Path.cwd()
    try:
        # Keep this test deterministic for relative-path resolution.
        os.chdir(tmp_path)
        resolved = resolve_save_dir(output, _DummyModel())
    finally:
        os.chdir(current)

    assert resolved.is_absolute()
    assert resolved == rel_save_dir.resolve()


def test_collect_optional_artifacts_copies_common_train_outputs(tmp_path: Path):
    save_dir = tmp_path / "yolo_train"
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "results.csv").write_text("epoch,loss\n1,1.0\n", encoding="utf-8")
    (save_dir / "args.yaml").write_text("epochs: 1\n", encoding="utf-8")
    (save_dir / "results.png").write_bytes(b"png")
    (save_dir / "BoxPR_curve.png").write_bytes(b"png")

    workspace = Workspace(str(tmp_path / "runs"), "step-1")
    workspace.ensure()

    artifacts = collect_optional_artifacts(save_dir=save_dir, workspace=workspace)
    names = {item.name for item in artifacts}

    assert "results.csv" in names
    assert "args.yaml" in names
    assert "results.png" in names
    assert "BoxPR_curve.png" in names
    assert (workspace.artifacts_dir / "results.csv").exists()
    assert (workspace.artifacts_dir / "args.yaml").exists()
