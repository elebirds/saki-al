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


def rect_to_vertices(rect: annotationirv1.RectGeometry) -> list[Point]:
    """返回 Rect 的 4 个顶点，顺序固定为 `TL, TR, BR, BL`。

    该顺序是屏幕坐标含义下的矩形角点顺序。
    """

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


def obb_to_vertices(obb: annotationirv1.ObbGeometry) -> list[Point]:
    """返回 OBB 的 4 个顶点，顺序固定为局部角点顺序 `TL, TR, BR, BL`。

    注意：这里的 `TL/TR/BR/BL` 是 OBB 局部坐标系中的角点定义，
    不是把结果点按屏幕坐标排序后的“最左上/最右上/...”。调用方不得重排顺序。
    """

    # Spec: docs/IR_SPEC.md#5-obb-semantics
    # Spec: docs/IR_SPEC.md#7-vertices-and-aabb
    cx = float(obb.cx)
    cy = float(obb.cy)
    w = float(obb.width)
    h = float(obb.height)
    theta = math.radians(float(obb.angle_deg_cw))
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
        rx = dx * cos_t + dy * sin_t
        ry = -dx * sin_t + dy * cos_t
        points.append((cx + rx, cy + ry))
    return points
