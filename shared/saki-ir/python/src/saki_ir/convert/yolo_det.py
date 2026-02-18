from __future__ import annotations

"""YOLOv5/YOLOv8 detection <-> saki-ir 转换（Step 1，纯语义层）。"""

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
    maybe_clip_rect,
    new_uuid,
    rect_ir_to_yolo,
    require_single_sample,
    split_batch,
    struct_to_dict,
    yolo_to_rect_ir,
)


def yolo_txt_to_ir(
    txt_text: str,
    *,
    image_w: int | None,
    image_h: int | None,
    class_names: list[str] | None,
    image_relpath: str | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """将 YOLO 检测文本转换为 DataBatchIR（单 sample）。"""

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
                        source="yolo",
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
            message="YOLO normalized 输入必须提供 image_w/image_h",
            source_ref=relpath,
        )
        return build_batch(None, [sample], None)

    labels: list[annotationirv1.LabelRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    class_key_to_label_id: dict[str, str] = {}

    for line_no, raw in enumerate(txt_text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 5:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"YOLO 行字段不足: {line}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        try:
            class_index = int(float(parts[0]))
            cx, cy, w, h = [float(parts[i]) for i in range(1, 5)]
        except ValueError:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"YOLO 行存在非法数值: {line}",
                source_ref=f"{relpath}:{line_no}",
            )
            continue

        if ctx.yolo_is_normalized:
            x, y, ww, hh = yolo_to_rect_ir(
                cx,
                cy,
                w,
                h,
                image_w=int(image_w or 0),
                image_h=int(image_h or 0),
                normalized=True,
            )
        else:
            x, y, ww, hh = yolo_to_rect_ir(
                cx,
                cy,
                w,
                h,
                image_w=max(int(image_w or 1), 1),
                image_h=max(int(image_h or 1), 1),
                normalized=False,
            )

        if not is_finite(x, y, ww, hh) or ww <= ctx.eps or hh <= ctx.eps:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_GEOMETRY,
                message=f"YOLO 框非法: x={x}, y={y}, w={ww}, h={hh}",
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

        ann = annotationirv1.AnnotationRecord(
            id=new_uuid(),
            sample_id=sample_id,
            label_id=label_id,
            source=annotationirv1.ANNOTATION_SOURCE_IMPORTED,
            confidence=1.0,
            geometry=annotationirv1.Geometry(rect=annotationirv1.RectGeometry(x=x, y=y, width=ww, height=hh)),
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


def ir_to_yolo_txt(
    batch: annotationirv1.DataBatchIR,
    *,
    image_w: int,
    image_h: int,
    class_to_index: dict[str, int] | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> str:
    """将 DataBatchIR（单 sample）导出为 YOLO 文本。

    若需要读取 warnings/errors（strict=False 时），请由调用方传入 `report`。
    """

    report = make_report(report, strict=ctx.strict)

    labels_by_id, samples, anns = split_batch(batch, ctx=ctx, report=report)
    sample = require_single_sample(
        samples,
        ctx=ctx,
        report=report,
        source_ref="batch.samples",
        target_name="YOLO",
    )
    if sample is None:
        return ""

    if ctx.yolo_is_normalized and (image_w <= 0 or image_h <= 0):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="YOLO normalized 导出必须提供正整数 image_w/image_h",
            source_ref="export.image_size",
        )
        return ""

    class_index = _build_class_index(batch=batch, labels_by_id=labels_by_id, class_to_index=class_to_index)
    clip_sample = annotationirv1.SampleRecord(id=sample.id, width=int(image_w), height=int(image_h))
    lines: list[str] = []
    precision = max(0, int(ctx.yolo_float_precision))

    for idx, ann in enumerate(anns):
        source_ref = f"annotation[{idx}]"
        if ann.sample_id != sample.id:
            continue

        if not ann.HasField("geometry") or ann.geometry.WhichOneof("shape") != "rect":
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_UNSUPPORTED,
                message="YOLO 导出仅支持 rect geometry",
                source_ref=source_ref,
            )
            continue

        rect = ann.geometry.rect
        x, y, w, h = float(rect.x), float(rect.y), float(rect.width), float(rect.height)

        clipped = maybe_clip_rect(
            x,
            y,
            w,
            h,
            sample=clip_sample,
            ctx=ctx,
            report=report,
            source_ref=source_ref,
        )
        if clipped is None:
            continue
        x, y, w, h = clipped

        cls_idx = _resolve_export_class_index(ann=ann, labels_by_id=labels_by_id, class_index=class_index)

        cx, cy, ww, hh = rect_ir_to_yolo(
            x,
            y,
            w,
            h,
            image_w=image_w,
            image_h=image_h,
            normalized=ctx.yolo_is_normalized,
        )

        if ctx.yolo_is_normalized:
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))
            ww = max(0.0, min(1.0, ww))
            hh = max(0.0, min(1.0, hh))

        lines.append(
            f"{cls_idx} "
            f"{cx:.{precision}f} "
            f"{cy:.{precision}f} "
            f"{ww:.{precision}f} "
            f"{hh:.{precision}f}"
        )

    return "\n".join(lines)


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
        label_name = item.label.name or item.label.id
        if label_name not in out:
            out[label_name] = next_idx
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
