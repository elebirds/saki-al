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

    # 首条是训练开始日志，后续每个 epoch 固定为 progress -> log(summary) -> metric
    epoch_rows = emitted[1:]
    assert [item[0] for item in epoch_rows] == [
        "progress",
        "log",
        "metric",
        "progress",
        "log",
        "metric",
    ]

    summary_log = epoch_rows[1][1]
    assert summary_log["meta"]["source"] == "worker_metric_summary"
    assert "loss=" in summary_log["message"]
    assert "map50=" in summary_log["message"]


def test_format_epoch_metric_summary_prioritizes_common_keys():
    text = _format_epoch_metric_summary(
        {"map50": 0.22, "extra": 1.0, "loss": 0.44, "precision": 0.33}
    )
    assert text.startswith("epoch metrics: loss=")
    assert "map50=" in text
    assert "precision=" in text
    assert "extra=" in text
