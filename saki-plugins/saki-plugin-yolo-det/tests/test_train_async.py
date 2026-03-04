from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saki_plugin_yolo_det.train_async import _format_epoch_metric_summary, run_train_with_epoch_stream
from saki_plugin_yolo_det.types import TrainConfig


class _WorkspaceStub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_dir = root / "data"
        self.step_id = "step-train-async"
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _make_train_config() -> TrainConfig:
    return TrainConfig(
        epochs=2,
        batch=4,
        imgsz=640,
        patience=5,
        device="cpu",
        requested_device="cpu",
        resolved_backend="cpu",
        resolved_base_model="yolo11n.pt",
        train_seed=0,
        deterministic=False,
        yolo_task="obb",
    )


@pytest.mark.anyio
async def test_run_train_with_epoch_stream_emits_progress_then_log_then_metric(tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    (workspace.data_dir / "dataset.yaml").write_text("path: .\ntrain: images\nval: images\n", encoding="utf-8")
    config = _make_train_config()

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    def _run_train_sync(**kwargs):
        callback = kwargs["epoch_callback"]
        callback(
            {
                "step": 1,
                "epoch": 1,
                "total_steps": 2,
                "eta_sec": 5,
                "metrics": {"loss": 0.5, "map50": 0.2},
            }
        )
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.4, "map50": 0.3},
            }
        )
        return {"metrics": {"loss": 0.4, "map50": 0.3}}

    await run_train_with_epoch_stream(
        workspace=workspace,  # type: ignore[arg-type]
        config=config,
        emit=_emit,
        run_train_sync=_run_train_sync,
        to_int=lambda value, default: int(value) if value is not None else default,
    )

    # 首条是训练开始日志，后续每个 epoch 固定为 progress -> metric
    epoch_rows = emitted[1:]
    assert [item[0] for item in epoch_rows] == [
        "progress",
        "metric",
        "progress",
        "metric",
    ]


@pytest.mark.anyio
async def test_run_train_with_epoch_stream_prefers_last_metric_callback_as_final_metrics(tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    (workspace.data_dir / "dataset.yaml").write_text("path: .\ntrain: images\nval: images\n", encoding="utf-8")
    config = _make_train_config()

    async def _emit(_event_type: str, _payload: dict[str, Any]) -> None:
        return None

    def _run_train_sync(**kwargs):
        callback = kwargs["epoch_callback"]
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.4, "map50": 0.3, "map50_95": 0.2, "precision": 0.5, "recall": 0.6},
            }
        )
        # simulate final best.pt validate callback on the same epoch
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.45, "map50": 0.35, "map50_95": 0.25, "precision": 0.55, "recall": 0.65},
            }
        )
        return {
            "metrics": {"loss": 0.4, "map50": 0.3, "map50_95": 0.2, "precision": 0.5, "recall": 0.6},
        }

    output = await run_train_with_epoch_stream(
        workspace=workspace,  # type: ignore[arg-type]
        config=config,
        emit=_emit,
        run_train_sync=_run_train_sync,
        to_int=lambda value, default: int(value) if value is not None else default,
    )

    assert output["metrics"]["loss"] == pytest.approx(0.45)
    assert output["metrics"]["map50"] == pytest.approx(0.35)
    assert output["metrics"]["map50_95"] == pytest.approx(0.25)
    assert output["metrics"]["precision"] == pytest.approx(0.55)
    assert output["metrics"]["recall"] == pytest.approx(0.65)


def test_format_epoch_metric_summary_prioritizes_common_keys():
    text = _format_epoch_metric_summary(
        {"map50": 0.22, "extra": 1.0, "loss": 0.44, "precision": 0.33}
    )
    assert text.startswith("epoch metrics: loss=")
    assert "map50=" in text
    assert "precision=" in text
    assert "extra=" in text
