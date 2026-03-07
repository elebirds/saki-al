from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from saki_plugin_sdk import Workspace
from saki_plugin_yolo_det.eval_service import YoloEvalService


class _ConfigStub:
    pass


class _FakeModel:
    def __init__(self, model_path: str, capture: dict[str, Any]) -> None:
        self._model_path = model_path
        self._capture = capture

    def val(self, **kwargs):
        project = Path(str(kwargs["project"]))
        name = str(kwargs.get("name") or "eval")
        save_dir = project / name
        save_dir.mkdir(parents=True, exist_ok=True)
        for filename in (
            "confusion_matrix.png",
            "confusion_matrix_normalized.png",
            "BoxF1_curve.png",
            "BoxPR_curve.png",
            "BoxP_curve.png",
            "BoxR_curve.png",
            "val_batch0_labels.jpg",
            "val_batch0_pred.jpg",
        ):
            (save_dir / filename).write_bytes(b"x")
        self._capture["project"] = str(project)
        return SimpleNamespace(
            results_dict={"metrics/mAP50(B)": 0.5},
            save_dir=str(save_dir),
        )


def test_eval_sync_collects_box_and_val_batch_artifacts(tmp_path):
    capture: dict[str, Any] = {}

    def _load_yolo():
        return lambda model_path: _FakeModel(model_path, capture)

    service = YoloEvalService(
        config_service=_ConfigStub(),
        load_yolo=_load_yolo,
        normalize_metrics=lambda payload: dict(payload or {}),
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-eval-1")
    workspace.ensure()
    dataset_yaml = workspace.data_dir / "dataset.yaml"
    dataset_yaml.write_text("path: data", encoding="utf-8")

    result = service._run_eval_sync(
        workspace=workspace,
        model_path="best.pt",
        dataset_yaml=dataset_yaml,
        imgsz=640,
        batch=8,
        device="cpu",
    )

    assert Path(str(capture["project"])).is_absolute()
    names = {Path(item).name for item in result["extra_artifacts"]}
    assert "confusion_matrix.png" in names
    assert "confusion_matrix_normalized.png" in names
    assert "BoxF1_curve.png" in names
    assert "BoxPR_curve.png" in names
    assert "BoxP_curve.png" in names
    assert "BoxR_curve.png" in names
    assert "val_batch0_labels.jpg" in names
    assert "val_batch0_pred.jpg" in names
