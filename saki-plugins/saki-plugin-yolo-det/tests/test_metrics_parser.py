from __future__ import annotations

import pytest

from saki_plugin_yolo_det.metrics_parser import normalize_metrics, parse_results_csv


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def test_normalize_metrics_aggregates_loss_components():
    row = {
        "metrics/mAP50(B)": 0.72,
        "metrics/mAP50-95(B)": 0.44,
        "metrics/precision(B)": 0.81,
        "metrics/recall(B)": 0.68,
        "train/box_loss": 0.2,
        "train/cls_loss": 0.3,
        "train/dfl_loss": 0.1,
    }

    metrics = normalize_metrics(row, _to_float)
    assert metrics["map50"] == 0.72
    assert metrics["map50_95"] == 0.44
    assert metrics["precision"] == 0.81
    assert metrics["recall"] == 0.68
    assert metrics["loss"] == pytest.approx(0.6)


def test_normalize_metrics_uses_partial_loss_components_when_available():
    row = {
        "train/box_loss": 0.25,
        "train/cls_loss": 0.15,
    }

    metrics = normalize_metrics(row, _to_float)
    assert metrics["loss"] == pytest.approx(0.4)


def test_normalize_metrics_falls_back_to_generic_loss_key():
    row = {
        "train/loss": 0.42,
    }

    metrics = normalize_metrics(row, _to_float)
    assert metrics["loss"] == pytest.approx(0.42)


def test_normalize_metrics_does_not_fill_missing_metrics_with_zero():
    metrics = normalize_metrics({"metrics/mAP50(B)": 0.66}, _to_float)
    assert metrics == {"map50": 0.66}


def test_parse_results_csv_includes_loss_column(tmp_path):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(
        "\n".join(
            [
                "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B),train/box_loss,train/cls_loss,train/dfl_loss",
                "0.66,0.39,0.78,0.64,0.12,0.23,0.10",
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_results_csv(csv_path, _to_float)
    assert len(rows) == 1
    assert rows[0]["loss"] == pytest.approx(0.45)
