from __future__ import annotations

import pytest

from saki_plugin_yolo_det.artifact_collector import extract_primary_metrics


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


class _DummyTrainOutput:
    pass


def test_extract_primary_metrics_backfills_loss_from_history():
    metrics = extract_primary_metrics(
        train_output=_DummyTrainOutput(),
        history=[{"map50": 0.71, "map50_95": 0.41, "precision": 0.8, "recall": 0.67, "loss": 0.33}],
        to_float=_to_float,
    )

    assert metrics["map50"] == pytest.approx(0.71)
    assert metrics["map50_95"] == pytest.approx(0.41)
    assert metrics["precision"] == pytest.approx(0.8)
    assert metrics["recall"] == pytest.approx(0.67)
    assert metrics["loss"] == pytest.approx(0.33)
