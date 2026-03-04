from __future__ import annotations

"""DOTA GT（poly8）<-> saki-ir OBB 转换。"""

import math
from collections.abc import Mapping
from typing import Any

from saki_ir.geom import obb_to_vertices_screen, rect_tl_to_center
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

from .base import (
    ERR_CONVERT_GEOMETRY,
    ERR_CONVERT_SCHEMA,
    ERR_CONVERT_UNSUPPORTED,
    ConversionContext,
    ConversionReport,
    build_batch,
    dict_to_struct,
    fail_or_report,
    is_finite,
    make_external_attrs,
    make_external_meta,
    make_report,
    new_uuid,
    require_single_sample,
    split_batch,
    struct_to_dict,
)


def dota_txt_to_ir(
    txt_text: str,
    *,
    image_w: int | None,
    image_h: int | None,
    class_names: list[str] | None,
    image_relpath: str | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """将单文件 DOTA labelTxt 文本转换为 DataBatchIR（单 sample）。"""

    report = make_report(report, strict=ctx.strict)
    width = int(image_w) if image_w is not None else 0
    height = int(image_h) if image_h is not None else 0

    sample_id = new_uuid()
    relpath = image_relpath or f"{sample_id}.png"
    sample = annotationirv1.SampleRecord(id=sample_id, width=width, height=height)

    declared = {str(name).strip() for name in (class_names or []) if str(name).strip()}

    imagesource = ""
    gsd_numeric: float | None = None
    gsd_raw_text = ""

    labels: list[annotationirv1.LabelRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    class_key_to_label_id: dict[str, str] = {}

    for line_no, raw in enumerate(txt_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        lower = line.lower()
        if lower.startswith("imagesource:"):
            imagesource = line.split(":", 1)[1].strip()
            continue
        if lower.startswith("gsd:"):
            gsd_text = line.split(":", 1)[1].strip()
            gsd_value = _parse_finite_float(gsd_text)
            if gsd_value is None and gsd_text:
                gsd_raw_text = gsd_text
                report.warn(f"{relpath}:{line_no}: gsd 非法，保留原始文本")
            else:
                gsd_numeric = gsd_value
            continue

        parts = line.split()
        if len(parts) not in {9, 10}:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"DOTA 列数非法，期望 9/10 列，实际={len(parts)}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        coords = _parse_poly8(parts[:8])
        if coords is None:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"DOTA 坐标非法: {line}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        class_name = str(parts[8]).strip()
        if not class_name:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="DOTA 类别为空",
                source_ref=f"{relpath}:{line_no}",
            )
            continue
        if declared and class_name not in declared:
            report.warn(f"{relpath}:{line_no}: 类别不在 declared class_names 中: {class_name}")

        difficulty = 0
        if len(parts) == 10:
            difficulty = _coerce_difficulty(parts[9], report=report, source_ref=f"{relpath}:{line_no}")

        obb_tuple = _fit_min_area_rect(points=coords, eps=ctx.eps)
        if obb_tuple is None:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_GEOMETRY,
                message="DOTA poly8 无法拟合为有效 OBB",
                source_ref=f"{relpath}:{line_no}",
            )
            continue
        cx, cy, w, h, angle_deg = obb_tuple

        label_id = class_key_to_label_id.get(class_name)
        if label_id is None:
            label_id = new_uuid()
            class_key_to_label_id[class_name] = label_id
            if ctx.emit_labels:
                labels.append(annotationirv1.LabelRecord(id=label_id, name=class_name))

        ann = annotationirv1.AnnotationRecord(
            id=new_uuid(),
            sample_id=sample_id,
            label_id=label_id,
            source=annotationirv1.ANNOTATION_SOURCE_IMPORTED,
            confidence=1.0,
            geometry=annotationirv1.Geometry(
                obb=annotationirv1.ObbGeometry(
                    cx=float(cx),
                    cy=float(cy),
                    width=float(w),
                    height=float(h),
                    angle_deg_ccw=float(angle_deg),
                )
            ),
        )

        attrs_payload: dict[str, Any] = {"dota": {"difficulty": int(difficulty)}}
        if ctx.include_external_ref:
            attrs_payload["external"] = make_external_attrs(
                ann_key=f"{relpath}:{line_no}",
                category_key=class_name,
                line=line_no,
            )
        ann.attrs.CopyFrom(dict_to_struct(attrs_payload))
        annotations.append(ann)

    meta_payload: dict[str, Any] = {}
    if ctx.include_external_ref:
        meta_payload["external"] = make_external_meta(
            source="dota",
            sample_key=relpath,
            file_name=relpath.split("/")[-1],
            relpath=relpath,
        )
    dota_meta: dict[str, Any] = {}
    if imagesource:
        dota_meta["imagesource"] = imagesource
    if gsd_numeric is not None:
        dota_meta["gsd"] = gsd_numeric
    elif gsd_raw_text:
        dota_meta["gsd"] = gsd_raw_text
    if dota_meta:
        meta_payload["dota"] = dota_meta
    if meta_payload:
        sample.meta.CopyFrom(dict_to_struct(meta_payload))

    return build_batch(labels if ctx.emit_labels else None, [sample], annotations)


def ir_to_dota_txt(
    batch: annotationirv1.DataBatchIR,
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> str:
    """将 DataBatchIR（单 sample）导出为 DOTA GT 文本。"""

    report = make_report(report, strict=ctx.strict)
    labels_by_id, samples, anns = split_batch(batch, ctx=ctx, report=report)
    sample = require_single_sample(
        samples,
        ctx=ctx,
        report=report,
        source_ref="batch.samples",
        target_name="DOTA",
    )
    if sample is None:
        return ""

    precision = max(0, int(ctx.yolo_float_precision))
    lines: list[str] = []

    imagesource, gsd = _extract_dota_headers(sample=sample)
    if imagesource:
        lines.append(f"imagesource:{imagesource}")
    if gsd:
        lines.append(f"gsd:{gsd}")

    for idx, ann in enumerate(anns):
        source_ref = f"annotation[{idx}]"
        if ann.sample_id != sample.id:
            continue

        obb = _ann_to_obb(ann=ann, ctx=ctx, report=report, source_ref=source_ref)
        if obb is None:
            continue

        points = obb_to_vertices_screen(obb)
        cls_name = _resolve_label_name(ann=ann, labels_by_id=labels_by_id)
        difficulty = _difficulty_from_attrs(ann=ann, report=report, source_ref=source_ref)

        flat: list[str] = []
        for x, y in points:
            flat.append(f"{float(x):.{precision}f}")
            flat.append(f"{float(y):.{precision}f}")
        lines.append(" ".join([*flat, cls_name, str(difficulty)]))

    return "\n".join(lines)


def _resolve_label_name(
    *,
    ann: annotationirv1.AnnotationRecord,
    labels_by_id: dict[str, annotationirv1.LabelRecord],
) -> str:
    label = labels_by_id.get(ann.label_id)
    if label is not None and str(label.name or "").strip():
        return str(label.name).strip()
    if str(ann.label_id or "").strip():
        return str(ann.label_id).strip()
    return "unknown"


def _extract_dota_headers(*, sample: annotationirv1.SampleRecord) -> tuple[str, str]:
    if not sample.HasField("meta"):
        return "", ""
    meta = struct_to_dict(sample.meta)
    if not isinstance(meta, Mapping):
        return "", ""
    dota = meta.get("dota")
    if not isinstance(dota, Mapping):
        return "", ""
    imagesource = str(dota.get("imagesource") or "").strip()
    gsd_raw = dota.get("gsd")
    if gsd_raw is None:
        gsd = ""
    else:
        gsd = _format_scalar(gsd_raw)
    return imagesource, gsd


def _format_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return ""
        text = f"{float(value):.12f}".rstrip("0").rstrip(".")
        return text if text else "0"
    return str(value).strip()


def _difficulty_from_attrs(
    *,
    ann: annotationirv1.AnnotationRecord,
    report: ConversionReport,
    source_ref: str,
) -> int:
    attrs = struct_to_dict(ann.attrs) if ann.HasField("attrs") else {}
    dotted = attrs.get("dota") if isinstance(attrs, Mapping) else None
    raw = dotted.get("difficulty", 0) if isinstance(dotted, Mapping) else 0
    parsed = _parse_non_negative_int(raw)
    if parsed is None:
        report.warn(f"{source_ref}: difficulty 非法，已回落为 0")
        return 0
    return parsed


def _ann_to_obb(
    *,
    ann: annotationirv1.AnnotationRecord,
    ctx: ConversionContext,
    report: ConversionReport,
    source_ref: str,
) -> annotationirv1.ObbGeometry | None:
    if not ann.HasField("geometry"):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="annotation.geometry 缺失",
            source_ref=source_ref,
        )
        return None

    shape = ann.geometry.WhichOneof("shape")
    if shape == "obb":
        obb = ann.geometry.obb
    elif shape == "rect":
        cx, cy, w, h = rect_tl_to_center(ann.geometry.rect)
        obb = annotationirv1.ObbGeometry(cx=cx, cy=cy, width=w, height=h, angle_deg_ccw=0.0)
    else:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_UNSUPPORTED,
            message="DOTA 导出仅支持 rect/obb geometry",
            source_ref=source_ref,
        )
        return None

    if not is_finite(obb.cx, obb.cy, obb.width, obb.height, obb.angle_deg_ccw):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_GEOMETRY,
            message="OBB 含 NaN/Inf",
            source_ref=source_ref,
        )
        return None
    if obb.width <= ctx.eps or obb.height <= ctx.eps:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_GEOMETRY,
            message="OBB width/height 非法",
            source_ref=source_ref,
        )
        return None

    out = annotationirv1.ObbGeometry()
    out.CopyFrom(obb)
    out.angle_deg_ccw = _normalize_angle_deg(float(out.angle_deg_ccw))
    return out


def _coerce_difficulty(value: Any, *, report: ConversionReport, source_ref: str) -> int:
    parsed = _parse_non_negative_int(value)
    if parsed is not None:
        return parsed
    report.warn(f"{source_ref}: difficult 非法，已回落为 0")
    return 0


def _parse_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_poly8(tokens: list[str]) -> list[tuple[float, float]] | None:
    if len(tokens) != 8:
        return None
    try:
        numbers = [float(item) for item in tokens]
    except ValueError:
        return None
    if not is_finite(*numbers):
        return None
    return [(numbers[index], numbers[index + 1]) for index in range(0, 8, 2)]


def _parse_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _fit_min_area_rect(
    *,
    points: list[tuple[float, float]],
    eps: float,
) -> tuple[float, float, float, float, float] | None:
    if len(points) != 4:
        return None
    if not all(is_finite(x, y) for x, y in points):
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
    for x, y in points:
        key = (float(x), float(y))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(key)

    if len(dedup) <= 1:
        return dedup
    dedup.sort()

    def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower: list[tuple[float, float]] = []
    for point in dedup:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(dedup):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def _normalize_angle_deg(angle: float) -> float:
    output = (float(angle) + 180.0) % 360.0 - 180.0
    if output >= 180.0:
        output -= 360.0
    return output


__all__ = [
    "dota_txt_to_ir",
    "ir_to_dota_txt",
]

