from __future__ import annotations

import numpy as np

from saki_plugin_oriented_rcnn.metrics_service import (
    build_eval_metrics,
    build_train_metrics,
    compute_micro_precision_recall,
    extract_map_metrics,
)


def test_extract_map_metrics_supports_dota_keys() -> None:
    map50, map50_95 = extract_map_metrics(
        {
            "dota/AP50": 0.73,
            "dota/mAP": 0.51,
        }
    )
    assert map50 == 0.73
    assert map50_95 == 0.51


def test_compute_micro_precision_recall_from_eval_details() -> None:
    details = [
        {
            "num_gts": 10,
            "recall": np.array([0.2, 0.6], dtype=np.float32),
            "precision": np.array([1.0, 0.75], dtype=np.float32),
        },
        {
            "num_gts": 5,
            "recall": np.array([0.4, 0.8], dtype=np.float32),
            "precision": np.array([0.8, 0.5], dtype=np.float32),
        },
    ]
    precision, recall = compute_micro_precision_recall(details)
    assert 0.0 <= precision <= 1.0
    assert 0.0 <= recall <= 1.0
    assert recall > 0.0


def test_build_train_metrics_contains_canonical_fields() -> None:
    metrics = build_train_metrics(
        raw_eval_metrics={"dota/AP50": 0.7, "dota/mAP": 0.5},
        eval_details=[],
        loss_value=0.33,
    ).to_train_metrics()
    assert set(metrics.keys()) == {"map50", "map50_95", "precision", "recall", "loss"}


def test_build_eval_metrics_contains_canonical_fields() -> None:
    metrics = build_eval_metrics(
        raw_eval_metrics={"AP50": 0.6, "mAP": 0.4},
        eval_details=[],
    ).to_eval_metrics()
    assert set(metrics.keys()) == {"map50", "map50_95", "precision", "recall"}
