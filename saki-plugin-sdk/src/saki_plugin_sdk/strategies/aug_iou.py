from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Any, Iterable, Sequence

try:
    from shapely.geometry import Polygon  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Polygon = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)
_SHAPELY_FALLBACK_WARNED = False
DEFAULT_IOU_MODE = "obb"
VALID_IOU_MODES = ("rect", "obb", "boundary")
DEFAULT_BOUNDARY_D = 3.0
MIN_BOUNDARY_D = 1.0
MAX_BOUNDARY_D = 128.0


@dataclass(frozen=True)
class DetectionBox:
    class_index: int
    confidence: float
    bounds: tuple[float, float, float, float]
    qbox: tuple[float, ...] | None = None


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


def _warn_shapely_fallback_once(message: str) -> None:
    global _SHAPELY_FALLBACK_WARNED
    if _SHAPELY_FALLBACK_WARNED:
        return
    _SHAPELY_FALLBACK_WARNED = True
    _LOGGER.warning(message)


def _normalize_iou_mode(mode: str | None) -> str:
    key = str(mode or "").strip().lower()
    if key in VALID_IOU_MODES:
        return key
    return DEFAULT_IOU_MODE


def _normalize_boundary_d(value: float | int | None) -> float:
    try:
        d = float(value if value is not None else DEFAULT_BOUNDARY_D)
    except Exception:
        d = DEFAULT_BOUNDARY_D
    if not math.isfinite(d):
        d = DEFAULT_BOUNDARY_D
    if d < MIN_BOUNDARY_D:
        return MIN_BOUNDARY_D
    if d > MAX_BOUNDARY_D:
        return MAX_BOUNDARY_D
    return d


def _axis_aligned_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
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


def _rect_area(a: tuple[float, float, float, float] | None) -> float:
    if a is None:
        return 0.0
    x1, y1, x2, y2 = a
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _rect_intersection_area(
    a: tuple[float, float, float, float] | None,
    b: tuple[float, float, float, float] | None,
) -> float:
    if a is None or b is None:
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    return iw * ih


def _expand_bounds(a: tuple[float, float, float, float], d: float) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = a
    return x1 - d, y1 - d, x2 + d, y2 + d


def _inner_bounds_or_none(
    a: tuple[float, float, float, float],
    d: float,
) -> tuple[float, float, float, float] | None:
    x1, y1, x2, y2 = a
    nx1 = x1 + d
    ny1 = y1 + d
    nx2 = x2 - d
    ny2 = y2 - d
    if nx2 <= nx1 or ny2 <= ny1:
        return None
    return nx1, ny1, nx2, ny2


def _boundary_iou_from_bounds(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    boundary_d: float,
) -> float:
    d = _normalize_boundary_d(boundary_d)
    outer_left = _expand_bounds(left, d)
    outer_right = _expand_bounds(right, d)
    inner_left = _inner_bounds_or_none(left, d)
    inner_right = _inner_bounds_or_none(right, d)

    area_left = _rect_area(outer_left) - _rect_area(inner_left)
    area_right = _rect_area(outer_right) - _rect_area(inner_right)

    inter = (
        _rect_intersection_area(outer_left, outer_right)
        - _rect_intersection_area(inner_left, outer_right)
        - _rect_intersection_area(outer_left, inner_right)
        + _rect_intersection_area(inner_left, inner_right)
    )
    inter = max(0.0, inter)

    union = area_left + area_right - inter
    if union <= 0.0:
        return 0.0
    return _clamp01(inter / union)


def _flatten_to_8_floats(value: Any) -> tuple[float, ...] | None:
    flat: list[float] = []

    def _walk(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            for child in item:
                _walk(child)
            return
        flat.append(float(item))

    try:
        _walk(value)
    except Exception:
        return None
    if len(flat) != 8:
        return None
    if any(not math.isfinite(v) for v in flat):
        return None
    return tuple(flat)


def _qbox_to_bounds(qbox: tuple[float, ...]) -> tuple[float, float, float, float]:
    xs = [qbox[0], qbox[2], qbox[4], qbox[6]]
    ys = [qbox[1], qbox[3], qbox[5], qbox[7]]
    return min(xs), min(ys), max(xs), max(ys)


def _obb_to_qbox(obb: dict[str, Any]) -> tuple[float, ...] | None:
    try:
        cx = float(obb.get("cx", 0.0))
        cy = float(obb.get("cy", 0.0))
        width = float(obb.get("width", 0.0))
        height = float(obb.get("height", 0.0))
        angle_deg_ccw = float(obb.get("angle_deg_ccw", 0.0))
    except Exception:
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    if not all(math.isfinite(v) for v in (cx, cy, width, height, angle_deg_ccw)):
        return None

    theta = math.radians(angle_deg_ccw)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    half_w = width / 2.0
    half_h = height / 2.0
    corners = [
        (-half_w, -half_h),
        (half_w, -half_h),
        (half_w, half_h),
        (-half_w, half_h),
    ]
    points: list[float] = []
    for dx, dy in corners:
        rx = dx * cos_t - dy * sin_t
        ry = dx * sin_t + dy * cos_t
        points.extend([cx + rx, cy + ry])
    return tuple(points)


def _polygon_iou_from_qbox(left_qbox: tuple[float, ...], right_qbox: tuple[float, ...]) -> float:
    left_bounds = _qbox_to_bounds(left_qbox)
    right_bounds = _qbox_to_bounds(right_qbox)
    if Polygon is None:
        _warn_shapely_fallback_once(
            "aug_iou: shapely 不可用，OBB/Boundary IoU 已退化为 AABB 近似计算。"
        )
        return _axis_aligned_iou(left_bounds, right_bounds)

    left_pts = [(float(left_qbox[i]), float(left_qbox[i + 1])) for i in (0, 2, 4, 6)]
    right_pts = [(float(right_qbox[i]), float(right_qbox[i + 1])) for i in (0, 2, 4, 6)]
    try:
        poly_left = Polygon(left_pts)
        poly_right = Polygon(right_pts)
        if not poly_left.is_valid:
            poly_left = poly_left.buffer(0)
        if not poly_right.is_valid:
            poly_right = poly_right.buffer(0)
        if poly_left.is_empty or poly_right.is_empty:
            return 0.0
        inter_area = float(poly_left.intersection(poly_right).area)
        union_area = float(poly_left.union(poly_right).area)
        if union_area <= 0.0:
            return 0.0
        return _clamp01(inter_area / union_area)
    except Exception:
        _warn_shapely_fallback_once(
            "aug_iou: shapely 几何计算失败，OBB/Boundary IoU 已退化为 AABB 近似计算。"
        )
        return _axis_aligned_iou(left_bounds, right_bounds)


def _boundary_iou_from_qbox(
    left_qbox: tuple[float, ...],
    right_qbox: tuple[float, ...],
    *,
    boundary_d: float,
) -> float:
    left_bounds = _qbox_to_bounds(left_qbox)
    right_bounds = _qbox_to_bounds(right_qbox)
    if Polygon is None:
        _warn_shapely_fallback_once(
            "aug_iou: shapely 不可用，OBB/Boundary IoU 已退化为 AABB 近似计算。"
        )
        return _boundary_iou_from_bounds(left_bounds, right_bounds, boundary_d=boundary_d)

    left_pts = [(float(left_qbox[i]), float(left_qbox[i + 1])) for i in (0, 2, 4, 6)]
    right_pts = [(float(right_qbox[i]), float(right_qbox[i + 1])) for i in (0, 2, 4, 6)]
    try:
        d = _normalize_boundary_d(boundary_d)
        poly_left = Polygon(left_pts)
        poly_right = Polygon(right_pts)
        if not poly_left.is_valid:
            poly_left = poly_left.buffer(0)
        if not poly_right.is_valid:
            poly_right = poly_right.buffer(0)
        if poly_left.is_empty or poly_right.is_empty:
            return 0.0

        outer_left = poly_left.buffer(d)
        outer_right = poly_right.buffer(d)
        inner_left = poly_left.buffer(-d)
        inner_right = poly_right.buffer(-d)
        ring_left = outer_left.difference(inner_left) if not inner_left.is_empty else outer_left
        ring_right = outer_right.difference(inner_right) if not inner_right.is_empty else outer_right
        if ring_left.is_empty or ring_right.is_empty:
            return 0.0
        inter_area = float(ring_left.intersection(ring_right).area)
        union_area = float(ring_left.union(ring_right).area)
        if union_area <= 0.0:
            return 0.0
        return _clamp01(inter_area / union_area)
    except Exception:
        _warn_shapely_fallback_once(
            "aug_iou: shapely 几何计算失败，OBB/Boundary IoU 已退化为 AABB 近似计算。"
        )
        return _boundary_iou_from_bounds(left_bounds, right_bounds, boundary_d=boundary_d)


def box_iou(
    a: DetectionBox,
    b: DetectionBox,
    *,
    iou_mode: str = DEFAULT_IOU_MODE,
    boundary_d: float = DEFAULT_BOUNDARY_D,
) -> float:
    mode = _normalize_iou_mode(iou_mode)
    if mode == "rect":
        return _axis_aligned_iou(a.bounds, b.bounds)
    if mode == "boundary":
        if a.qbox is not None and b.qbox is not None:
            return _boundary_iou_from_qbox(a.qbox, b.qbox, boundary_d=boundary_d)
        return _boundary_iou_from_bounds(a.bounds, b.bounds, boundary_d=boundary_d)

    if a.qbox is not None and b.qbox is not None:
        return _polygon_iou_from_qbox(a.qbox, b.qbox)
    return _axis_aligned_iou(a.bounds, b.bounds)


def _hungarian_maximize(weights: list[list[float]]) -> list[tuple[int, int]]:
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

    inf_cost = max_weight + 1.0
    cost = [[inf_cost for _ in range(n)] for _ in range(n)]
    for i in range(rows):
        for j in range(cols):
            cost[i][j] = max_weight - weights[i][j]

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
    classes = {item.class_index for item in anchor} | {item.class_index for item in other}
    if not classes:
        return 0.0
    total_a = len(anchor)
    total_b = len(other)
    if total_a == 0 and total_b == 0:
        return 0.0

    gap = 0.0
    for class_index in classes:
        pa = _safe_div(sum(1 for x in anchor if x.class_index == class_index), total_a)
        pb = _safe_div(sum(1 for x in other if x.class_index == class_index), total_b)
        gap += abs(pa - pb)
    return _clamp01(gap * 0.5)


def _pair_mean_iou_by_class(
    anchor: Sequence[DetectionBox],
    other: Sequence[DetectionBox],
    *,
    iou_mode: str,
    boundary_d: float,
) -> float:
    classes = {item.class_index for item in anchor} | {item.class_index for item in other}
    if not classes:
        return 1.0

    matched_ious: list[float] = []
    for class_index in classes:
        a_cls = [x for x in anchor if x.class_index == class_index]
        b_cls = [x for x in other if x.class_index == class_index]
        if not a_cls and not b_cls:
            continue
        if not a_cls or not b_cls:
            matched_ious.append(0.0)
            continue
        matrix = [[box_iou(a, b, iou_mode=iou_mode, boundary_d=boundary_d) for b in b_cls] for a in a_cls]
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
    *,
    iou_mode: str = DEFAULT_IOU_MODE,
    boundary_d: float = DEFAULT_BOUNDARY_D,
) -> tuple[float, dict[str, float]]:
    """
    Augmentation IoU disagreement scoring (fixed formula):
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
        confidence_mean = _safe_div(sum(float(x.confidence) for x in only), len(only))
        score = 0.15 * confidence_mean
        return _clamp01(score), {
            "mean_iou": 1.0,
            "count_gap": 0.0,
            "class_gap": 0.0,
            "conf_std": 0.0,
            "score": _clamp01(score),
        }

    mode = _normalize_iou_mode(iou_mode)
    norm_boundary_d = _normalize_boundary_d(boundary_d)
    anchor = list(predictions_by_aug[0])
    others = [list(item) for item in predictions_by_aug[1:]]

    mean_iou_items: list[float] = []
    count_gap_items: list[float] = []
    class_gap_items: list[float] = []

    for other in others:
        mean_iou_items.append(
            _pair_mean_iou_by_class(
                anchor,
                other,
                iou_mode=mode,
                boundary_d=norm_boundary_d,
            )
        )
        count_gap_items.append(
            _safe_div(abs(len(anchor) - len(other)), max(1, max(len(anchor), len(other))))
        )
        class_gap_items.append(_class_hist_gap(anchor, other))

    mean_iou = _safe_div(sum(mean_iou_items), len(mean_iou_items))
    count_gap = _safe_div(sum(count_gap_items), len(count_gap_items))
    class_gap = _safe_div(sum(class_gap_items), len(class_gap_items))

    conf_means = [
        _safe_div(sum(float(item.confidence) for item in aug_pred), len(aug_pred))
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
        try:
            geometry = row.get("geometry")
            qbox = _flatten_to_8_floats(row.get("qbox"))
            if qbox is None and isinstance(geometry, dict):
                qbox = _flatten_to_8_floats(geometry.get("qbox"))
            if qbox is None and isinstance(geometry, dict):
                obb = geometry.get("obb")
                if isinstance(obb, dict):
                    qbox = _obb_to_qbox(obb)

            if qbox is not None:
                x1, y1, x2, y2 = _qbox_to_bounds(qbox)
            else:
                rect = geometry.get("rect") if isinstance(geometry, dict) else None
                if not isinstance(rect, dict):
                    continue
                x1 = float(rect.get("x", 0.0))
                y1 = float(rect.get("y", 0.0))
                width = float(rect.get("width", 0.0))
                height = float(rect.get("height", 0.0))
                x2 = x1 + max(0.0, width)
                y2 = y1 + max(0.0, height)
            class_index = int(row.get("class_index", 0))
            confidence = float(row.get("confidence", 0.0))
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append(
            DetectionBox(
                class_index=class_index,
                confidence=_clamp01(confidence),
                bounds=(x1, y1, x2, y2),
                qbox=qbox,
            )
        )
    return boxes


if Polygon is None:  # pragma: no cover - depends on optional dependency
    _warn_shapely_fallback_once(
        "aug_iou: shapely 不可用，OBB/Boundary IoU 已退化为 AABB 近似计算。"
    )
