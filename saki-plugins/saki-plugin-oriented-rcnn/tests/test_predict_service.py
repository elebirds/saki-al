from __future__ import annotations

import itertools
import math
import threading

import pytest

from saki_plugin_oriented_rcnn.config_service import OrientedRCNNConfigService
from saki_plugin_oriented_rcnn.predict_service import (
    OrientedRCNNPredictService,
    _hungarian_maximize,
    _polygon_iou,
    _stable_random_score,
)


def _assignment_score(matrix: list[list[float]], pairs: list[tuple[int, int]]) -> float:
    return sum(float(matrix[i][j]) for i, j in pairs)


def _bruteforce_best_score(matrix: list[list[float]]) -> float:
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    if rows == 0 or cols == 0:
        return 0.0

    k = min(rows, cols)
    best = 0.0
    if rows <= cols:
        for col_perm in itertools.permutations(range(cols), k):
            score = sum(float(matrix[r][col_perm[r]]) for r in range(rows))
            best = max(best, score)
    else:
        for row_perm in itertools.permutations(range(rows), k):
            score = sum(float(matrix[row_perm[c]][c]) for c in range(cols))
            best = max(best, score)
    return best


def test_hungarian_maximize_matches_bruteforce_optimal() -> None:
    # 关键验证：匈牙利实现要和暴力搜索的最优值一致，避免匹配逻辑隐性退化。
    matrix = [
        [0.2, 0.9, 0.4],
        [0.8, 0.1, 0.5],
    ]
    pairs = _hungarian_maximize(matrix)
    actual = _assignment_score(matrix, pairs)
    expected = _bruteforce_best_score(matrix)
    assert math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8)


def test_polygon_iou_fallback_without_shapely(monkeypatch: pytest.MonkeyPatch) -> None:
    # 关键验证：当 shapely 不可用时，必须退化到 AABB IoU，且结果可预测。
    import saki_plugin_oriented_rcnn.predict_service as predict_service

    monkeypatch.setattr(predict_service, "Polygon", None)
    left = (0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0)
    right = (1.0, 0.0, 3.0, 0.0, 3.0, 2.0, 1.0, 2.0)
    iou = _polygon_iou(left, right)
    assert math.isclose(iou, 1.0 / 3.0, rel_tol=1e-6, abs_tol=1e-6)


def test_aug_iou_disagreement_boundary_inputs() -> None:
    service = OrientedRCNNPredictService(
        stop_flag=threading.Event(),
        config_service=OrientedRCNNConfigService(),
    )

    # 空输入：返回 0 分，且 reason 结构完整。
    score_empty, reason_empty = service._score_aug_iou_disagreement([])
    assert score_empty == 0.0
    assert set(reason_empty.keys()) == {"mean_iou", "count_gap", "class_gap", "conf_std", "score"}

    # 单分支输入：走边界公式 score=0.15*mean_conf。
    single = [[{"confidence": 0.6}, {"confidence": 0.8}]]
    score_single, reason_single = service._score_aug_iou_disagreement(single)
    assert math.isclose(score_single, 0.105, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(reason_single["score"], score_single, rel_tol=1e-6, abs_tol=1e-6)

    # 两个完全一致的分支：不一致性应接近 0（稳定样本不该被高分选中）。
    qbox = (0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0)
    same_left = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    same_right = [
        {"class_index": 0, "confidence": 0.9, "qbox": qbox},
        {"class_index": 1, "confidence": 0.7, "qbox": qbox},
    ]
    score_same, reason_same = service._score_aug_iou_disagreement([same_left, same_right])
    assert math.isclose(score_same, 0.0, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(reason_same["mean_iou"], 1.0, rel_tol=1e-6, abs_tol=1e-6)


def test_random_baseline_score_is_stable_for_same_seed_and_pool() -> None:
    first = _stable_random_score(sample_id="sample-a", random_seed=101)
    second = _stable_random_score(sample_id="sample-a", random_seed=101)
    third = _stable_random_score(sample_id="sample-b", random_seed=101)
    assert first == second
    assert first != third
