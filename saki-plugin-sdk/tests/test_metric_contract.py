from __future__ import annotations

import pytest

from saki_plugin_sdk.metric_contract import (
    EVAL_REQUIRED_KEYS,
    TRAIN_REQUIRED_KEYS,
    validate_final_metrics,
    validate_metric_event,
)


def test_validate_final_metrics_train_requires_all_canonical_keys():
    metrics = validate_final_metrics(
        step_type="train",
        metrics={"map50": 0.5, "map50_95": 0.3, "precision": 0.8, "recall": 0.7},
    )
    assert metrics == {"map50": 0.5, "map50_95": 0.3, "precision": 0.8, "recall": 0.7}


def test_validate_final_metrics_eval_requires_all_canonical_keys():
    metrics = validate_final_metrics(
        step_type="eval",
        metrics={"map50": 0.5, "precision": 0.8},
    )
    assert metrics == {"map50": 0.5, "precision": 0.8}


def test_validate_final_metrics_rejects_non_canonical_keys():
    with pytest.raises(Exception, match="METRIC_CONTRACT_VIOLATION"):
        validate_final_metrics(
            step_type="train",
            metrics={
                "map50": 0.5,
                "map50_95": 0.3,
                "precision": 0.8,
                "recall": 0.7,
                "loss": 0.2,
                "metrics/mAP50(B)": 0.55,
            },
        )


def test_validate_final_metrics_rejects_non_finite_values():
    with pytest.raises(Exception, match="METRIC_CONTRACT_VIOLATION"):
        validate_final_metrics(
            step_type="train",
            metrics={
                "map50": 0.5,
                "map50_95": 0.3,
                "precision": 0.8,
                "recall": 0.7,
                "loss": float("nan"),
            },
        )


def test_validate_metric_event_train_allows_canonical_subset():
    metrics = validate_metric_event(
        step_type="train",
        metrics={"loss": 0.2, "map50": 0.51},
        is_final=False,
    )
    assert metrics == {"loss": 0.2, "map50": 0.51}


def test_validate_metric_event_eval_requires_exact_canonical_set():
    metrics = validate_metric_event(
        step_type="eval",
        metrics={"map50": 0.61, "precision": 0.77},
        is_final=True,
    )
    assert metrics == {"map50": 0.61, "precision": 0.77}


def test_validate_final_metrics_allows_empty_mapping():
    assert validate_final_metrics(step_type="train", metrics={}) == {}
    assert validate_final_metrics(step_type="eval", metrics={}) == {}


def test_validate_final_metrics_returns_ordered_canonical_payload():
    train_metrics = validate_final_metrics(
        step_type="train",
        metrics={key: idx + 1 for idx, key in enumerate(TRAIN_REQUIRED_KEYS)},
    )
    assert list(train_metrics.keys()) == list(TRAIN_REQUIRED_KEYS)

    eval_metrics = validate_final_metrics(
        step_type="eval",
        metrics={key: idx + 1 for idx, key in enumerate(EVAL_REQUIRED_KEYS)},
    )
    assert list(eval_metrics.keys()) == list(EVAL_REQUIRED_KEYS)
