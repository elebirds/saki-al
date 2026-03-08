from __future__ import annotations

import math

import pytest

from saki_plugin_sdk.strategies.aug_iou import build_detection_boxes, score_aug_iou_disagreement
from saki_plugin_sdk.strategies.builtin import (
    CANONICAL_AUG_IOU_STRATEGY,
    CANONICAL_RANDOM_STRATEGY,
    CANONICAL_UNCERTAINTY_STRATEGY,
    score_aug_iou_disagreement_from_rows,
    score_by_strategy,
    score_random_baseline,
    score_uncertainty_1_minus_max_conf,
)


def test_random_baseline_is_stable_and_round_invariant() -> None:
    first, _ = score_random_baseline("sample-a", random_seed=11)
    second, _ = score_random_baseline("sample-a", random_seed=11)
    third, _ = score_random_baseline("sample-b", random_seed=11)
    assert first == second
    assert first != third

    via_round_1, _ = score_by_strategy(CANONICAL_RANDOM_STRATEGY, "sample-a", random_seed=11, round_index=1)
    via_round_9, _ = score_by_strategy(CANONICAL_RANDOM_STRATEGY, "sample-a", random_seed=11, round_index=9)
    assert via_round_1 == via_round_9


def test_uncertainty_scores_empty_single_multi_and_clamp() -> None:
    score_empty, reason_empty = score_uncertainty_1_minus_max_conf([])
    assert score_empty == 1.0
    assert reason_empty["pred_count"] == 0

    score_single, _ = score_uncertainty_1_minus_max_conf([{"confidence": 0.8}])
    assert math.isclose(score_single, 0.2, rel_tol=1e-6, abs_tol=1e-6)

    score_multi, _ = score_uncertainty_1_minus_max_conf([
        {"confidence": -0.5},
        {"confidence": 0.3},
        {"confidence": 1.8},
    ])
    assert math.isclose(score_multi, 0.0, rel_tol=1e-6, abs_tol=1e-6)


def test_aug_iou_route_matches_core_function() -> None:
    rows_by_aug = [
        [
            {
                "class_index": 0,
                "confidence": 0.9,
                "geometry": {"rect": {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0}},
            }
        ],
        [
            {
                "class_index": 0,
                "confidence": 0.8,
                "geometry": {"rect": {"x": 1.0, "y": 0.0, "width": 10.0, "height": 10.0}},
            }
        ],
    ]
    score_route, reason_route = score_aug_iou_disagreement_from_rows(rows_by_aug)

    boxes = [build_detection_boxes(rows) for rows in rows_by_aug]
    score_core, reason_core = score_aug_iou_disagreement(boxes)

    assert math.isclose(score_route, score_core, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(float(reason_route["score"]), float(reason_core["score"]), rel_tol=1e-9, abs_tol=1e-9)
    assert reason_route["strategy"] == CANONICAL_AUG_IOU_STRATEGY


def test_score_by_strategy_strict_mode_and_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="requires predictions"):
        score_by_strategy(CANONICAL_UNCERTAINTY_STRATEGY, "sample-a")

    with pytest.raises(ValueError, match="requires predictions_by_aug"):
        score_by_strategy(CANONICAL_AUG_IOU_STRATEGY, "sample-a")

    with pytest.raises(ValueError, match="unsupported strategy"):
        score_by_strategy("custom_strategy_x", "sample-a")

    score_u, reason_u = score_by_strategy(
        CANONICAL_UNCERTAINTY_STRATEGY,
        "sample-a",
        predictions=[{"confidence": 0.6}],
    )
    assert math.isclose(score_u, 0.4, rel_tol=1e-6, abs_tol=1e-6)
    assert reason_u["strategy"] == CANONICAL_UNCERTAINTY_STRATEGY
