from __future__ import annotations

import math

import pytest

from saki_plugin_sdk.strategies.builtin import (
    CANONICAL_AUG_IOU_STRATEGY,
    CANONICAL_RANDOM_STRATEGY,
    CANONICAL_UNCERTAINTY_STRATEGY,
    score_aug_iou_disagreement_from_rows,
    score_by_strategy,
    score_random_baseline,
)


def test_aug_iou_disagreement_boundary_inputs() -> None:
    score_empty, reason_empty = score_aug_iou_disagreement_from_rows([])
    assert score_empty == 0.0
    assert set(reason_empty.keys()) == {
        "strategy",
        "mean_iou",
        "count_gap",
        "class_gap",
        "conf_std",
        "score",
    }

    single = [[
        {"class_index": 0, "confidence": 0.6, "geometry": {"rect": {"x": 0.0, "y": 0.0, "width": 2.0, "height": 2.0}}},
        {"class_index": 0, "confidence": 0.8, "geometry": {"rect": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0}}},
    ]]
    score_single, reason_single = score_aug_iou_disagreement_from_rows(single)
    assert math.isclose(score_single, 0.105, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(reason_single["score"]), score_single, rel_tol=1e-6, abs_tol=1e-6)

    qbox = (0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0)
    same_left = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    same_right = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    score_same, reason_same = score_aug_iou_disagreement_from_rows([same_left, same_right])
    assert math.isclose(score_same, 0.0, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(float(reason_same["mean_iou"]), 1.0, rel_tol=1e-6, abs_tol=1e-6)


def test_random_baseline_score_is_stable_for_same_seed_and_pool() -> None:
    first, _ = score_random_baseline("sample-a", random_seed=101)
    second, _ = score_random_baseline("sample-a", random_seed=101)
    third, _ = score_random_baseline("sample-b", random_seed=101)
    assert first == second
    assert first != third


def test_score_by_strategy_is_strict_on_required_inputs() -> None:
    with pytest.raises(ValueError, match="requires predictions"):
        score_by_strategy(CANONICAL_UNCERTAINTY_STRATEGY, "sample-a", random_seed=1)

    with pytest.raises(ValueError, match="requires predictions_by_aug"):
        score_by_strategy(CANONICAL_AUG_IOU_STRATEGY, "sample-a", random_seed=1)


def test_score_by_strategy_routes_three_canonical_strategies() -> None:
    random_score, random_reason = score_by_strategy(CANONICAL_RANDOM_STRATEGY, "sample-a", random_seed=7)
    assert 0.0 <= random_score <= 1.0
    assert random_reason["strategy"] == CANONICAL_RANDOM_STRATEGY

    uncertainty_score, uncertainty_reason = score_by_strategy(
        CANONICAL_UNCERTAINTY_STRATEGY,
        "sample-a",
        predictions=[{"confidence": 0.85}],
    )
    assert math.isclose(uncertainty_score, 0.15, rel_tol=1e-6, abs_tol=1e-6)
    assert uncertainty_reason["strategy"] == CANONICAL_UNCERTAINTY_STRATEGY

    aug_score, aug_reason = score_by_strategy(
        CANONICAL_AUG_IOU_STRATEGY,
        "sample-a",
        predictions_by_aug=[[{"confidence": 0.6}], [{"confidence": 0.8}]],
    )
    assert 0.0 <= aug_score <= 1.0
    assert aug_reason["strategy"] == CANONICAL_AUG_IOU_STRATEGY
