from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DetectionBox:
    cls_id: int
    conf: float
    xyxy: tuple[float, float, float, float]


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def box_iou(a: DetectionBox, b: DetectionBox) -> float:
    ax1, ay1, ax2, ay2 = a.xyxy
    bx1, by1, bx2, by2 = b.xyxy

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter_area = iw * ih
    if inter_area <= 0.0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return _clamp01(_safe_div(inter_area, union))


def _hungarian_maximize(weights: list[list[float]]) -> list[tuple[int, int]]:
    """最大权匹配（矩阵可非方阵）。返回 (row_idx, col_idx) 对。"""
    if not weights or not weights[0]:
        return []

    rows = len(weights)
    cols = len(weights[0])
    n = max(rows, cols)
    max_weight = 0.0
    for row in weights:
        for value in row:
            if value > max_weight:
                max_weight = value

    # 转换为最小化代价矩阵（补齐为方阵）
    inf_cost = max_weight + 1.0
    cost = [[inf_cost for _ in range(n)] for _ in range(n)]
    for i in range(rows):
        for j in range(cols):
            cost[i][j] = max_weight - weights[i][j]

    # Kuhn-Munkres (Hungarian), 1-indexed implementation.
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment: list[tuple[int, int]] = []
    for j in range(1, n + 1):
        i = p[j]
        if i == 0:
            continue
        row_idx = i - 1
        col_idx = j - 1
        if row_idx < rows and col_idx < cols:
            assignment.append((row_idx, col_idx))
    return assignment


def _class_hist_gap(anchor: Sequence[DetectionBox], other: Sequence[DetectionBox]) -> float:
    classes = {item.cls_id for item in anchor} | {item.cls_id for item in other}
    if not classes:
        return 0.0
    total_a = len(anchor)
    total_b = len(other)
    if total_a == 0 and total_b == 0:
        return 0.0

    gap = 0.0
    for cls_id in classes:
        pa = _safe_div(sum(1 for x in anchor if x.cls_id == cls_id), total_a)
        pb = _safe_div(sum(1 for x in other if x.cls_id == cls_id), total_b)
        gap += abs(pa - pb)
    # 离散分布 L1 距离归一化到 [0, 1]
    return _clamp01(gap * 0.5)


def _pair_mean_iou_by_class(anchor: Sequence[DetectionBox], other: Sequence[DetectionBox]) -> float:
    classes = {item.cls_id for item in anchor} | {item.cls_id for item in other}
    if not classes:
        return 1.0

    matched_ious: list[float] = []
    for cls_id in classes:
        a_cls = [x for x in anchor if x.cls_id == cls_id]
        b_cls = [x for x in other if x.cls_id == cls_id]
        if not a_cls and not b_cls:
            continue
        if not a_cls or not b_cls:
            matched_ious.append(0.0)
            continue
        matrix = [[box_iou(a, b) for b in b_cls] for a in a_cls]
        pairs = _hungarian_maximize(matrix)
        if not pairs:
            matched_ious.append(0.0)
            continue
        cls_iou_values = [matrix[i][j] for i, j in pairs]
        matched_ious.append(sum(cls_iou_values) / len(cls_iou_values))
    if not matched_ious:
        return 1.0
    return _clamp01(sum(matched_ious) / len(matched_ious))


def score_aug_iou_disagreement(
    predictions_by_aug: Sequence[Sequence[DetectionBox]],
) -> tuple[float, dict[str, float]]:
    """
    增强 IoU 分歧打分（固定公式）:
    score = 0.45*(1-mean_iou) + 0.2*count_gap + 0.2*class_gap + 0.15*conf_std
    """
    if not predictions_by_aug:
        return 0.0, {
            "mean_iou": 1.0,
            "count_gap": 0.0,
            "class_gap": 0.0,
            "conf_std": 0.0,
            "score": 0.0,
        }
    if len(predictions_by_aug) == 1:
        only = predictions_by_aug[0]
        conf_mean = _safe_div(sum(float(x.conf) for x in only), len(only))
        score = 0.15 * conf_mean
        return _clamp01(score), {
            "mean_iou": 1.0,
            "count_gap": 0.0,
            "class_gap": 0.0,
            "conf_std": 0.0,
            "score": _clamp01(score),
        }

    anchor = list(predictions_by_aug[0])
    others = [list(item) for item in predictions_by_aug[1:]]

    mean_iou_items: list[float] = []
    count_gap_items: list[float] = []
    class_gap_items: list[float] = []

    for other in others:
        mean_iou_items.append(_pair_mean_iou_by_class(anchor, other))
        count_gap_items.append(
            _safe_div(abs(len(anchor) - len(other)), max(1, max(len(anchor), len(other))))
        )
        class_gap_items.append(_class_hist_gap(anchor, other))

    mean_iou = _safe_div(sum(mean_iou_items), len(mean_iou_items))
    count_gap = _safe_div(sum(count_gap_items), len(count_gap_items))
    class_gap = _safe_div(sum(class_gap_items), len(class_gap_items))

    conf_means = [
        _safe_div(sum(float(item.conf) for item in aug_pred), len(aug_pred))
        for aug_pred in predictions_by_aug
    ]
    mean_conf = _safe_div(sum(conf_means), len(conf_means))
    conf_var = _safe_div(sum((value - mean_conf) ** 2 for value in conf_means), len(conf_means))
    conf_std = _clamp01(math.sqrt(max(0.0, conf_var)))

    score = (
        0.45 * (1.0 - _clamp01(mean_iou))
        + 0.2 * _clamp01(count_gap)
        + 0.2 * _clamp01(class_gap)
        + 0.15 * conf_std
    )
    score = _clamp01(score)

    return score, {
        "mean_iou": _clamp01(mean_iou),
        "count_gap": _clamp01(count_gap),
        "class_gap": _clamp01(class_gap),
        "conf_std": conf_std,
        "score": score,
    }


def build_detection_boxes(rows: Iterable[dict]) -> list[DetectionBox]:
    boxes: list[DetectionBox] = []
    for row in rows:
        xyxy_raw = row.get("xyxy")
        if not isinstance(xyxy_raw, (list, tuple)) or len(xyxy_raw) != 4:
            continue
        try:
            x1, y1, x2, y2 = [float(v) for v in xyxy_raw]
            cls_id = int(row.get("cls_id", 0))
            conf = float(row.get("conf", 0.0))
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append(DetectionBox(cls_id=cls_id, conf=_clamp01(conf), xyxy=(x1, y1, x2, y2)))
    return boxes
