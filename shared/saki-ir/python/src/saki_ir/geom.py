from __future__ import annotations

"""saki-ir 几何计算工具函数。

Spec: docs/IR_SPEC.md#4-rect-semantics
Spec: docs/IR_SPEC.md#5-obb-semantics
Spec: docs/IR_SPEC.md#7-vertices-and-aabb
"""

import math
from typing import TypeAlias

from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

Point: TypeAlias = tuple[float, float]
_SORT_EPS = 1e-6


def rect_tl_to_center(rect: annotationirv1.RectGeometry) -> tuple[float, float, float, float]:
    """将 Rect(TL) 转为 `(cx, cy, w, h)`。"""

    # Spec: docs/IR_SPEC.md#4-rect-semantics
    cx = float(rect.x) + float(rect.width) / 2.0
    cy = float(rect.y) + float(rect.height) / 2.0
    return cx, cy, float(rect.width), float(rect.height)


def rect_center_to_tl(cx: float, cy: float, width: float, height: float) -> tuple[float, float, float, float]:
    """将中心表示转为 Rect(TL) 的 `(x, y, w, h)`。"""

    # Spec: docs/IR_SPEC.md#4-rect-semantics
    x = float(cx) - float(width) / 2.0
    y = float(cy) - float(height) / 2.0
    return x, y, float(width), float(height)


def rect_to_vertices_screen(rect: annotationirv1.RectGeometry) -> list[Point]:
    """返回 Rect 的 4 个顶点，顺序固定为屏幕 `TL, TR, BR, BL`。"""

    # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
    x = float(rect.x)
    y = float(rect.y)
    w = float(rect.width)
    h = float(rect.height)
    return [
        (x, y),
        (x + w, y),
        (x + w, y + h),
        (x, y + h),
    ]


def rect_to_vertices(rect: annotationirv1.RectGeometry) -> list[Point]:
    """兼容别名：等价 `rect_to_vertices_screen`。"""

    return rect_to_vertices_screen(rect)


def obb_to_vertices_local(obb: annotationirv1.ObbGeometry) -> list[Point]:
    """返回 OBB 的 4 个顶点，顺序固定为局部角点顺序 `TL, TR, BR, BL`。

    注意：这里的 `TL/TR/BR/BL` 是 OBB 局部坐标系角点，不是屏幕排序结果。
    """

    # Spec: docs/IR_SPEC.md#5-obb-semantics
    # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
    cx = float(obb.cx)
    cy = float(obb.cy)
    w = float(obb.width)
    h = float(obb.height)
    theta = math.radians(float(obb.angle_deg_ccw))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    half_w = w / 2.0
    half_h = h / 2.0
    corners = [
        (-half_w, -half_h),
        (half_w, -half_h),
        (half_w, half_h),
        (-half_w, half_h),
    ]

    points: list[Point] = []
    for dx, dy in corners:
        # Spec: docs/IR_SPEC.md#5-obb-semantics
        # 屏幕坐标 CCW 旋转（x 右, y 下）
        rx = dx * cos_t - dy * sin_t
        ry = dx * sin_t + dy * cos_t
        points.append((cx + rx, cy + ry))
    return points


def obb_to_vertices_screen(obb: annotationirv1.ObbGeometry, *, eps: float = _SORT_EPS) -> list[Point]:
    """返回 OBB 的屏幕排序角点 `TL, TR, BR, BL`。"""

    # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
    local = obb_to_vertices_local(obb)
    return _sort_vertices_screen(local, eps=eps)


def obb_to_vertices(obb: annotationirv1.ObbGeometry) -> list[Point]:
    """兼容别名：等价 `obb_to_vertices_local`。"""

    return obb_to_vertices_local(obb)


def vertices_to_aabb(vertices: list[Point]) -> tuple[float, float, float, float]:
    """由顶点集合计算 AABB `(x, y, w, h)`。"""

    if not vertices:
        return 0.0, 0.0, 0.0, 0.0
    xs = [float(p[0]) for p in vertices]
    ys = [float(p[1]) for p in vertices]
    x0 = min(xs)
    y0 = min(ys)
    x1 = max(xs)
    y1 = max(ys)
    return x0, y0, x1 - x0, y1 - y0


def _sort_vertices_screen(points: list[Point], *, eps: float) -> list[Point]:
    """按屏幕规则将 4 点排序为 `TL, TR, BR, BL`。"""

    if len(points) != 4:
        raise ValueError("screen 顶点排序要求输入 4 个点")

    scale = 1.0 / eps if eps > 0 else 0.0

    def q(v: float) -> float:
        if scale == 0.0:
            return v
        return round(v * scale)

    by_yx = sorted(points, key=lambda p: (q(float(p[1])), q(float(p[0])), float(p[1]), float(p[0])))
    top = sorted(by_yx[:2], key=lambda p: (q(float(p[0])), float(p[0]), q(float(p[1])), float(p[1])))
    bottom = sorted(by_yx[2:], key=lambda p: (q(float(p[0])), float(p[0]), q(float(p[1])), float(p[1])))
    return [top[0], top[1], bottom[1], bottom[0]]
