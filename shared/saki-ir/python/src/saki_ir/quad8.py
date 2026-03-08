from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from google.protobuf.json_format import ParseDict

from saki_ir.geom import obb_to_vertices_local, rect_to_vertices_screen
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

Quad8FitMode = Literal["strict", "min_area", "strict_then_min_area"]


def normalize_quad8(value: Any) -> tuple[float, ...] | None:
    flat: list[float] = []

    def _walk(item: Any) -> None:
        if hasattr(item, "tolist") and not isinstance(item, (str, bytes, bytearray)):
            _walk(item.tolist())
            return
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


def geometry_to_quad8_local(geometry_proto_or_payload: Any) -> tuple[float, ...]:
    geometry = _parse_geometry(geometry_proto_or_payload)
    shape = geometry.WhichOneof("shape")
    if shape == "rect":
        points = rect_to_vertices_screen(geometry.rect)
    elif shape == "obb":
        points = obb_to_vertices_local(geometry.obb)
    else:
        raise ValueError("geometry must include rect or obb")
    out: list[float] = []
    for x, y in points:
        out.extend([float(x), float(y)])
    return tuple(out)


def quad8_to_aabb_rect(quad8: Any) -> tuple[float, float, float, float]:
    normalized = normalize_quad8(quad8)
    if normalized is None:
        raise ValueError("quad8 must contain exactly 8 finite numeric values")
    xs = [normalized[0], normalized[2], normalized[4], normalized[6]]
    ys = [normalized[1], normalized[3], normalized[5], normalized[7]]
    x0 = float(min(xs))
    y0 = float(min(ys))
    x1 = float(max(xs))
    y1 = float(max(ys))
    return x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)


def flip_quad8(
    quad8: Any,
    *,
    op: str,
    width: int | float,
    height: int | float,
) -> tuple[float, ...]:
    normalized = normalize_quad8(quad8)
    if normalized is None:
        raise ValueError("quad8 must contain exactly 8 finite numeric values")

    op_key = str(op or "").strip().lower()
    if op_key not in {"identity", "bright", "hflip", "vflip"}:
        raise ValueError(f"unsupported flip op: {op}")

    w = float(width)
    h = float(height)
    if not math.isfinite(w) or not math.isfinite(h) or w <= 0.0 or h <= 0.0:
        raise ValueError("width/height must be finite positive numbers")

    out: list[float] = []
    for i in range(0, 8, 2):
        x = float(normalized[i])
        y = float(normalized[i + 1])
        if op_key == "hflip":
            x = w - x
        elif op_key == "vflip":
            y = h - y
        x = max(0.0, min(w, x))
        y = max(0.0, min(h, y))
        out.extend([x, y])
    return tuple(out)


def quad8_to_obb_payload(
    quad8: Any,
    *,
    fit_mode: Quad8FitMode = "strict_then_min_area",
    eps: float = 1e-6,
) -> dict[str, dict[str, float]]:
    normalized = normalize_quad8(quad8)
    if normalized is None:
        raise ValueError("quad8 must contain exactly 8 finite numeric values")

    points = [(float(normalized[i]), float(normalized[i + 1])) for i in range(0, 8, 2)]
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        raise ValueError("quad8 contains non-finite values")

    if fit_mode == "strict":
        fitted = _poly8_to_obb_strict(points=points, eps=float(eps))
    elif fit_mode == "min_area":
        fitted = _fit_min_area_rect(points=points, eps=float(eps))
    elif fit_mode == "strict_then_min_area":
        fitted = _poly8_to_obb_strict(points=points, eps=float(eps))
        if fitted is None:
            fitted = _fit_min_area_rect(points=points, eps=float(eps))
    else:
        raise ValueError(f"unsupported fit_mode: {fit_mode}")

    if fitted is None:
        raise ValueError("quad8 cannot be fitted into a valid OBB")

    cx, cy, width, height, angle_deg = fitted
    return {
        "obb": {
            "cx": float(cx),
            "cy": float(cy),
            "width": float(width),
            "height": float(height),
            "angle_deg_ccw": float(_normalize_angle_deg(angle_deg)),
        }
    }


def _parse_geometry(value: Any) -> annotationirv1.Geometry:
    if isinstance(value, annotationirv1.Geometry):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("geometry payload must be a mapping")
    out = annotationirv1.Geometry()
    ParseDict(dict(value), out, ignore_unknown_fields=False)
    shape = out.WhichOneof("shape")
    if shape not in {"rect", "obb"}:
        raise ValueError("geometry must include rect or obb")
    return out


def _poly8_to_obb_strict(
    *,
    points: list[tuple[float, float]],
    eps: float,
) -> tuple[float, float, float, float, float] | None:
    if len(points) != 4:
        return None

    cx = sum(p[0] for p in points) / 4.0
    cy = sum(p[1] for p in points) / 4.0
    ordered = sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

    vecs = [
        (
            ordered[(i + 1) % 4][0] - ordered[i][0],
            ordered[(i + 1) % 4][1] - ordered[i][1],
        )
        for i in range(4)
    ]
    lens = [math.hypot(vx, vy) for vx, vy in vecs]
    if any(l <= eps for l in lens):
        return None

    ortho_tol = 0.05
    side_tol = 0.10
    for i in range(4):
        vx1, vy1 = vecs[i]
        vx2, vy2 = vecs[(i + 1) % 4]
        dot = vx1 * vx2 + vy1 * vy2
        if abs(dot) / (lens[i] * lens[(i + 1) % 4]) > ortho_tol:
            return None

    if abs(lens[0] - lens[2]) > max(lens[0], lens[2]) * side_tol:
        return None
    if abs(lens[1] - lens[3]) > max(lens[1], lens[3]) * side_tol:
        return None

    width = (lens[0] + lens[2]) / 2.0
    height = (lens[1] + lens[3]) / 2.0
    if width <= eps or height <= eps:
        return None

    vx, vy = vecs[0]
    angle_deg = _normalize_angle_deg(math.degrees(math.atan2(vy, vx)))
    return cx, cy, width, height, angle_deg


def _fit_min_area_rect(
    *,
    points: list[tuple[float, float]],
    eps: float,
) -> tuple[float, float, float, float, float] | None:
    if len(points) != 4:
        return None
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        return None

    hull = _convex_hull(points)
    if len(hull) < 3:
        return None

    best: tuple[float, float, float, float, float, float] | None = None
    for idx in range(len(hull)):
        x0, y0 = hull[idx]
        x1, y1 = hull[(idx + 1) % len(hull)]
        dx = x1 - x0
        dy = y1 - y0
        edge_len = math.hypot(dx, dy)
        if edge_len <= eps:
            continue

        theta = math.atan2(dy, dx)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        rotated = [(x * cos_t + y * sin_t, -x * sin_t + y * cos_t) for x, y in hull]
        xs = [item[0] for item in rotated]
        ys = [item[1] for item in rotated]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        width = max_x - min_x
        height = max_y - min_y
        if width <= eps or height <= eps:
            continue

        area = width * height
        center_x_local = (min_x + max_x) / 2.0
        center_y_local = (min_y + max_y) / 2.0
        center_x = center_x_local * cos_t - center_y_local * sin_t
        center_y = center_x_local * sin_t + center_y_local * cos_t

        candidate = (
            area,
            center_x,
            center_y,
            width,
            height,
            _normalize_angle_deg(math.degrees(theta)),
        )
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return None
    _, cx, cy, width, height, angle = best
    return cx, cy, width, height, angle


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    dedup: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for point in points:
        key = (float(point[0]), float(point[1]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(key)
    if len(dedup) <= 1:
        return dedup

    sorted_points = sorted(dedup)

    def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in sorted_points:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(sorted_points):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def _normalize_angle_deg(angle: float) -> float:
    out = (float(angle) + 180.0) % 360.0 - 180.0
    if out >= 180.0:
        out -= 360.0
    return out


__all__ = [
    "Quad8FitMode",
    "normalize_quad8",
    "geometry_to_quad8_local",
    "quad8_to_aabb_rect",
    "flip_quad8",
    "quad8_to_obb_payload",
]
