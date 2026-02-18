from __future__ import annotations

"""YOLO OBB（rbox/poly8）<-> saki-ir 转换（Step 1，纯语义层）。"""

import math

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

_AUTO_RAD_MAX = 2.0 * math.pi + 0.5


def yolo_obb_txt_to_ir(
    txt_text: str,
    *,
    image_w: int | None,
    image_h: int | None,
    class_names: list[str] | None,
    image_relpath: str | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """将 YOLO OBB 文本转换为 DataBatchIR（单 sample）。

    支持行格式：
    - `cls cx cy w h angle`（rbox，6列）
    - `cls x1 y1 x2 y2 x3 y3 x4 y4`（poly8，9列）

    导入格式选择：
    - `ctx.yolo_label_format == "obb_rbox"`：仅接受 6 列
    - `ctx.yolo_label_format == "obb_poly8"`：仅接受 9 列
    - 其他值（例如默认 det）允许混合导入 6/9 列，导出再由 fmt 控制
    """

    report = make_report(report, strict=ctx.strict)

    width = int(image_w) if image_w is not None else 0
    height = int(image_h) if image_h is not None else 0

    sample_id = new_uuid()
    sample = annotationirv1.SampleRecord(id=sample_id, width=width, height=height)

    relpath = image_relpath or f"{sample_id}.jpg"
    if ctx.include_external_ref:
        sample.meta.CopyFrom(
            dict_to_struct(
                {
                    "external": make_external_meta(
                        source="yolo_obb",
                        sample_key=relpath,
                        file_name=relpath.split("/")[-1],
                        relpath=relpath,
                    )
                }
            )
        )

    if ctx.yolo_is_normalized and (image_w is None or image_h is None or image_w <= 0 or image_h <= 0):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="YOLO OBB normalized 输入必须提供 image_w/image_h",
            source_ref=relpath,
        )
        return build_batch(None, [sample], None)

    if ctx.yolo_obb_angle_unit not in ("deg", "rad", "auto"):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"不支持的 yolo_obb_angle_unit: {ctx.yolo_obb_angle_unit}",
            source_ref="ctx.yolo_obb_angle_unit",
        )
        return build_batch(None, [sample], None)

    allowed_cols = _allowed_column_counts(ctx.yolo_label_format)

    labels: list[annotationirv1.LabelRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    class_key_to_label_id: dict[str, str] = {}

    for line_no, raw in enumerate(txt_text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) not in allowed_cols:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"YOLO OBB 列数非法，当前={len(parts)}，允许={sorted(allowed_cols)}: {line}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        try:
            class_index = int(float(parts[0]))
        except ValueError:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"YOLO OBB 类别索引非法: {line}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        class_key = str(class_index)
        label_name = _resolve_class_name(class_index, class_names)
        label_id = class_key_to_label_id.get(class_key)
        if label_id is None:
            label_id = new_uuid()
            class_key_to_label_id[class_key] = label_id
            if ctx.emit_labels:
                labels.append(annotationirv1.LabelRecord(id=label_id, name=label_name))

        obb = _parse_line_to_obb(
            parts=parts,
            ctx=ctx,
            image_w=image_w,
            image_h=image_h,
            source_ref=f"{relpath}:{line_no}",
            report=report,
        )
        if obb is None:
            continue

        ann = annotationirv1.AnnotationRecord(
            id=new_uuid(),
            sample_id=sample_id,
            label_id=label_id,
            source=annotationirv1.ANNOTATION_SOURCE_IMPORTED,
            confidence=1.0,
            geometry=annotationirv1.Geometry(obb=obb),
        )

        if ctx.include_external_ref:
            ann.attrs.CopyFrom(
                dict_to_struct(
                    {
                        "external": make_external_attrs(
                            ann_key=f"{relpath}:{line_no}",
                            category_key=class_key,
                            line=line_no,
                        )
                    }
                )
            )

        annotations.append(ann)

    return build_batch(labels if ctx.emit_labels else None, [sample], annotations)


def ir_to_yolo_obb_txt(
    batch: annotationirv1.DataBatchIR,
    *,
    image_w: int,
    image_h: int,
    class_to_index: dict[str, int] | None,
    fmt: str,
    angle_unit: str,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> str:
    """将 DataBatchIR（单 sample）导出为 YOLO OBB 文本。"""

    report = make_report(report, strict=ctx.strict)

    if fmt not in ("rbox", "poly8"):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"不支持的 OBB 导出格式: {fmt}",
            source_ref="fmt",
        )
        return ""

    if angle_unit not in ("deg", "rad"):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"不支持的 angle_unit: {angle_unit}",
            source_ref="angle_unit",
        )
        return ""

    labels_by_id, samples, anns = split_batch(batch, ctx=ctx, report=report)
    sample = require_single_sample(
        samples,
        ctx=ctx,
        report=report,
        source_ref="batch.samples",
        target_name="YOLO OBB",
    )
    if sample is None:
        return ""

    if ctx.yolo_is_normalized and (image_w <= 0 or image_h <= 0):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="YOLO OBB normalized 导出必须提供正整数 image_w/image_h",
            source_ref="export.image_size",
        )
        return ""

    class_index = _build_class_index(batch=batch, labels_by_id=labels_by_id, class_to_index=class_to_index)
    precision = max(0, int(ctx.yolo_float_precision))
    lines: list[str] = []

    for idx, ann in enumerate(anns):
        source_ref = f"annotation[{idx}]"
        if ann.sample_id != sample.id:
            continue

        obb = _ann_to_obb(ann=ann, ctx=ctx, report=report, source_ref=source_ref)
        if obb is None:
            continue

        cls_idx = _resolve_export_class_index(ann=ann, labels_by_id=labels_by_id, class_index=class_index)

        if fmt == "rbox":
            cx = float(obb.cx)
            cy = float(obb.cy)
            w = float(obb.width)
            h = float(obb.height)
            angle_deg = _normalize_angle_deg(float(obb.angle_deg_ccw))

            if ctx.yolo_is_normalized:
                cx = _clamp01(cx / float(image_w))
                cy = _clamp01(cy / float(image_h))
                w = _clamp01(w / float(image_w))
                h = _clamp01(h / float(image_h))

            angle = angle_deg if angle_unit == "deg" else math.radians(angle_deg)
            lines.append(
                f"{cls_idx} "
                f"{cx:.{precision}f} "
                f"{cy:.{precision}f} "
                f"{w:.{precision}f} "
                f"{h:.{precision}f} "
                f"{angle:.{precision}f}"
            )
            continue

        points = obb_to_vertices_screen(obb)
        flat: list[str] = []
        for x, y in points:
            if ctx.yolo_is_normalized:
                x = _clamp01(x / float(image_w))
                y = _clamp01(y / float(image_h))
            flat.append(f"{x:.{precision}f}")
            flat.append(f"{y:.{precision}f}")
        lines.append(f"{cls_idx} " + " ".join(flat))

    return "\n".join(lines)


def _parse_line_to_obb(
    *,
    parts: list[str],
    ctx: ConversionContext,
    image_w: int | None,
    image_h: int | None,
    source_ref: str,
    report: ConversionReport,
) -> annotationirv1.ObbGeometry | None:
    if len(parts) == 6:
        return _parse_rbox_to_obb(
            values=parts[1:],
            ctx=ctx,
            image_w=image_w,
            image_h=image_h,
            source_ref=source_ref,
            report=report,
        )

    if len(parts) == 9:
        return _parse_poly8_to_obb(
            values=parts[1:],
            ctx=ctx,
            image_w=image_w,
            image_h=image_h,
            source_ref=source_ref,
            report=report,
        )

    fail_or_report(
        ctx=ctx,
        report=report,
        code=ERR_CONVERT_SCHEMA,
        message=f"YOLO OBB 行列数非法: {len(parts)}",
        source_ref=source_ref,
    )
    return None


def _parse_rbox_to_obb(
    *,
    values: list[str],
    ctx: ConversionContext,
    image_w: int | None,
    image_h: int | None,
    source_ref: str,
    report: ConversionReport,
) -> annotationirv1.ObbGeometry | None:
    if len(values) != 5:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"rbox 期望 5 个数值，实际={len(values)}",
            source_ref=source_ref,
        )
        return None

    try:
        cx, cy, w, h, angle_raw = [float(v) for v in values]
    except ValueError:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"YOLO OBB rbox 数值非法: {' '.join(values)}",
            source_ref=source_ref,
        )
        return None

    if ctx.yolo_is_normalized:
        cx *= float(image_w or 0)
        cy *= float(image_h or 0)
        w *= float(image_w or 0)
        h *= float(image_h or 0)

    angle_deg = _normalize_angle_deg(_parse_angle_to_deg(angle_raw, unit=ctx.yolo_obb_angle_unit))

    if not is_finite(cx, cy, w, h, angle_deg) or w <= ctx.eps or h <= ctx.eps:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_GEOMETRY,
            message=f"YOLO OBB rbox 非法: cx={cx}, cy={cy}, w={w}, h={h}, angle={angle_deg}",
            source_ref=source_ref,
        )
        return None

    return annotationirv1.ObbGeometry(
        cx=float(cx),
        cy=float(cy),
        width=float(w),
        height=float(h),
        angle_deg_ccw=float(angle_deg),
    )


def _parse_poly8_to_obb(
    *,
    values: list[str],
    ctx: ConversionContext,
    image_w: int | None,
    image_h: int | None,
    source_ref: str,
    report: ConversionReport,
) -> annotationirv1.ObbGeometry | None:
    if len(values) != 8:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"poly8 期望 8 个数值，实际={len(values)}",
            source_ref=source_ref,
        )
        return None

    try:
        nums = [float(v) for v in values]
    except ValueError:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"YOLO OBB poly8 数值非法: {' '.join(values)}",
            source_ref=source_ref,
        )
        return None

    points = [(nums[i], nums[i + 1]) for i in range(0, 8, 2)]
    if ctx.yolo_is_normalized:
        points = [(x * float(image_w or 0), y * float(image_h or 0)) for x, y in points]

    if not all(is_finite(x, y) for x, y in points):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_GEOMETRY,
            message="YOLO OBB poly8 含 NaN/Inf",
            source_ref=source_ref,
        )
        return None

    rect = _poly8_to_obb(points=points, eps=ctx.eps)
    if rect is None:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_UNSUPPORTED,
            message="poly8 无法可靠矩形化为 OBB（当前 proto 不支持 polygon）",
            source_ref=source_ref,
        )
        return None

    cx, cy, w, h, angle_deg = rect
    return annotationirv1.ObbGeometry(
        cx=float(cx),
        cy=float(cy),
        width=float(w),
        height=float(h),
        angle_deg_ccw=float(angle_deg),
    )


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
            message="YOLO OBB 导出仅支持 rect/obb geometry",
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


def _poly8_to_obb(
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


def _parse_angle_to_deg(angle: float, *, unit: str) -> float:
    if unit == "deg":
        return float(angle)
    if unit == "rad":
        return math.degrees(float(angle))
    # auto: 常见弧度范围大致在 [-2*pi, 2*pi] 附近，超出则按度处理。
    if abs(float(angle)) <= _AUTO_RAD_MAX:
        return math.degrees(float(angle))
    return float(angle)


def _normalize_angle_deg(angle: float) -> float:
    out = (float(angle) + 180.0) % 360.0 - 180.0
    if out >= 180.0:
        out -= 360.0
    return out


def _allowed_column_counts(label_format: str) -> set[int]:
    if label_format == "obb_rbox":
        return {6}
    if label_format == "obb_poly8":
        return {9}
    return {6, 9}


def _resolve_class_name(class_index: int, class_names: list[str] | None) -> str:
    if class_names and 0 <= class_index < len(class_names):
        return str(class_names[class_index])
    return f"class_{class_index}"


def _build_class_index(
    *,
    batch: annotationirv1.DataBatchIR,
    labels_by_id: dict[str, annotationirv1.LabelRecord],
    class_to_index: dict[str, int] | None,
) -> dict[str, int]:
    if class_to_index is not None:
        return dict(class_to_index)

    out: dict[str, int] = {}
    next_idx = 0

    for item in batch.items:
        if item.WhichOneof("item") != "label":
            continue
        name = item.label.name or item.label.id
        if name not in out:
            out[name] = next_idx
            next_idx += 1

    for item in batch.items:
        if item.WhichOneof("item") != "annotation":
            continue
        ann = item.annotation
        label_name = labels_by_id.get(ann.label_id).name if ann.label_id in labels_by_id else ann.label_id
        if label_name not in out:
            out[label_name] = next_idx
            next_idx += 1

    return out


def _resolve_export_class_index(
    *,
    ann: annotationirv1.AnnotationRecord,
    labels_by_id: dict[str, annotationirv1.LabelRecord],
    class_index: dict[str, int],
) -> int:
    label = labels_by_id.get(ann.label_id)
    label_name = label.name if label is not None and label.name else ann.label_id
    if label_name in class_index:
        return class_index[label_name]

    if label is not None and label.id in class_index:
        return class_index[label.id]

    attrs = struct_to_dict(ann.attrs) if ann.HasField("attrs") else {}
    external = attrs.get("external", {}) if isinstance(attrs, dict) else {}
    category_key = str(external.get("category_key", ""))
    if category_key.isdigit():
        return int(category_key)

    return 0


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))
