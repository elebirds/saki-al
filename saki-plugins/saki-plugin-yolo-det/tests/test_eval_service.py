from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from saki_plugin_sdk import Workspace
from saki_plugin_yolo_det.eval_service import YoloEvalService


class _ConfigStub:
    def resolve_config(self, _params: dict[str, Any]) -> Any:
        return SimpleNamespace(imgsz=640, batch=8, device="cpu")

    async def resolve_best_or_fallback_model(self, *, workspace: Workspace, params: Any) -> str:
        del workspace, params
        return "best.pt"


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
        run_name="eval_test",
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


@pytest.mark.anyio
async def test_eval_runs_three_scopes_and_uses_anchor_as_primary(tmp_path, monkeypatch):
    service = YoloEvalService(
        config_service=_ConfigStub(),
        load_yolo=lambda: None,
        normalize_metrics=lambda payload: dict(payload or {}),
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-eval-three-scope")
    workspace.ensure()
    (workspace.data_dir / "dataset.yaml").write_text(
        '{"path":"%s","train":"images/train","val":"images/val","names":{"0":"ship"}}'
        % str(workspace.data_dir.resolve()),
        encoding="utf-8",
    )
    (workspace.data_dir / "dataset_manifest.json").write_text(
        '{"snapshot_partition_sample_ids":{"test_anchor":["a1","a2"],"test_batch":["b1"]}}',
        encoding="utf-8",
    )
    (workspace.data_dir / "images" / "train").mkdir(parents=True, exist_ok=True)
    (workspace.data_dir / "images" / "val").mkdir(parents=True, exist_ok=True)
    for sample_id in ("a1", "a2", "b1"):
        (workspace.data_dir / "images" / "train" / f"{sample_id}.jpg").write_bytes(b"x")

    def _fake_run_eval_sync(**kwargs):
        run_name = str(kwargs.get("run_name") or "")
        if run_name.endswith("test_anchor"):
            return {"metrics": {"map50": 0.8, "map50_95": 0.7, "precision": 0.9, "recall": 0.6}, "extra_artifacts": [], "sample_count": 2}
        if run_name.endswith("test_batch"):
            return {"metrics": {"map50": 0.3, "map50_95": 0.2, "precision": 0.4, "recall": 0.5}, "extra_artifacts": [], "sample_count": 1}
        return {"metrics": {"map50": 0.6, "map50_95": 0.5, "precision": 0.7, "recall": 0.55}, "extra_artifacts": [], "sample_count": 3}

    monkeypatch.setattr(service, "_run_eval_sync", _fake_run_eval_sync)

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
        profile_id="cpu",
        task_context=SimpleNamespace(mode="active_learning"),
    )
    output = await service.eval(
        workspace=workspace,  # type: ignore[arg-type]
        params={},
        emit=_emit,
        context=context,  # type: ignore[arg-type]
    )

    assert output.metrics["map50"] == pytest.approx(0.8)
    metric_steps = [int(payload.get("step") or 0) for event_type, payload in emitted if event_type == "metric"]
    assert metric_steps == [1, 2, 3]
    report = json.loads((workspace.artifacts_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert report["primary_scope"] == "test_anchor"
    assert report["sample_count_by_scope"]["test_anchor"] == 2
    assert report["sample_count_by_scope"]["test_batch"] == 1
    assert report["sample_count_by_scope"]["test_composite"] == 3


@pytest.mark.anyio
async def test_eval_falls_back_when_anchor_metrics_missing(tmp_path, monkeypatch):
    service = YoloEvalService(
        config_service=_ConfigStub(),
        load_yolo=lambda: None,
        normalize_metrics=lambda payload: dict(payload or {}),
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-eval-fallback")
    workspace.ensure()
    (workspace.data_dir / "dataset.yaml").write_text(
        '{"path":"%s","train":"images/train","val":"images/val","names":{"0":"ship"}}'
        % str(workspace.data_dir.resolve()),
        encoding="utf-8",
    )
    (workspace.data_dir / "dataset_manifest.json").write_text(
        '{"snapshot_partition_sample_ids":{"test_anchor":["a1"],"test_batch":["b1"]}}',
        encoding="utf-8",
    )
    (workspace.data_dir / "images" / "train").mkdir(parents=True, exist_ok=True)
    (workspace.data_dir / "images" / "val").mkdir(parents=True, exist_ok=True)
    for sample_id in ("a1", "b1"):
        (workspace.data_dir / "images" / "train" / f"{sample_id}.jpg").write_bytes(b"x")

    def _fake_run_eval_sync(**kwargs):
        run_name = str(kwargs.get("run_name") or "")
        if run_name.endswith("test_anchor"):
            return {"metrics": {}, "extra_artifacts": [], "sample_count": 1}
        if run_name.endswith("test_batch"):
            return {"metrics": {"map50": 0.2, "map50_95": 0.1, "precision": 0.3, "recall": 0.4}, "extra_artifacts": [], "sample_count": 1}
        return {"metrics": {"map50": 0.6, "map50_95": 0.5, "precision": 0.7, "recall": 0.8}, "extra_artifacts": [], "sample_count": 2}

    monkeypatch.setattr(service, "_run_eval_sync", _fake_run_eval_sync)

    async def _emit(_event_type: str, _payload: dict[str, Any]) -> None:
        return None

    context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
        profile_id="cpu",
        task_context=SimpleNamespace(mode="active_learning"),
    )
    output = await service.eval(
        workspace=workspace,  # type: ignore[arg-type]
        params={},
        emit=_emit,
        context=context,  # type: ignore[arg-type]
    )

    assert output.metrics["map50"] == pytest.approx(0.6)
    report = json.loads((workspace.artifacts_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert report["primary_scope"] == "test_composite"
    assert report["metric_validation"]["fallback_applied"] is True
