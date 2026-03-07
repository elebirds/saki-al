from __future__ import annotations

"""COCO detection <-> saki-ir 转换（Step 1，纯语义层）。"""

from typing import Any

from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

from .base import (
    ERR_CONVERT_GEOMETRY,
    ERR_CONVERT_SCHEMA,
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
    split_batch,
    struct_to_dict,
)


def coco_to_ir(
    coco: dict[str, Any],
    *,
    image_root: str | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """将 COCO instances 字典转换为 DataBatchIR。

    仅做注释语义转换，不做目录扫描、文件重命名。
    `image_root` 在 Step1 中保留但不使用。
    """

    _ = image_root  # Step1 不参与路径扫描，保留形参兼容。
    report = make_report(report, strict=ctx.strict)

    labels: list[annotationirv1.LabelRecord] = []
    samples: list[annotationirv1.SampleRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []

    categories = coco.get("categories") or []
    images = coco.get("images") or []
    anns = coco.get("annotations") or []

    category_to_label_id: dict[Any, str] = {}

    for i, cat in enumerate(categories):
        source_ref = f"categories[{i}]"
        cat_id = cat.get("id")
        if cat_id is None:
            fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_SCHEMA, message="COCO category.id 缺失", source_ref=source_ref)
            continue

        name = str(cat.get("name") or f"category_{cat_id}")
        label_id = new_uuid()
        category_to_label_id[cat_id] = label_id

        if ctx.emit_labels:
            labels.append(annotationirv1.LabelRecord(id=label_id, name=name))

    image_to_sample_id: dict[Any, str] = {}
    for i, image in enumerate(images):
        source_ref = f"images[{i}]"
        image_id = image.get("id")
        if image_id is None:
            fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_SCHEMA, message="COCO image.id 缺失", source_ref=source_ref)
            continue

        try:
            width = int(image.get("width"))
            height = int(image.get("height"))
        except (TypeError, ValueError):
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="COCO image.width/height 非法",
                source_ref=source_ref,
            )
            continue

        sample_id = new_uuid()
        image_to_sample_id[image_id] = sample_id

        sample = annotationirv1.SampleRecord(
            id=sample_id,
            width=width,
            height=height,
            download_url=str(image.get("coco_url") or ""),
        )

        if ctx.include_external_ref:
            external = make_external_meta(
                source="coco",
                sample_key=str(image_id),
                file_name=str(image.get("file_name") or ""),
                relpath=str(image.get("file_name") or ""),
            )
            sample.meta.CopyFrom(dict_to_struct({"external": external}))

        samples.append(sample)

    for i, ann in enumerate(anns):
        source_ref = f"annotations[{i}]"
        image_id = ann.get("image_id")
        category_id = ann.get("category_id")
        bbox = ann.get("bbox")

        if image_id not in image_to_sample_id:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"annotation 引用了不存在的 image_id={image_id}",
                source_ref=source_ref,
            )
            continue

        if category_id not in category_to_label_id:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"annotation 引用了不存在的 category_id={category_id}",
                source_ref=source_ref,
            )
            continue

        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_SCHEMA, message="COCO bbox 必须是长度4数组", source_ref=source_ref)
            continue

        try:
            x, y, w, h = [float(v) for v in bbox]
        except (TypeError, ValueError):
            fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_SCHEMA, message="COCO bbox 含非法值", source_ref=source_ref)
            continue

        if not is_finite(x, y, w, h) or w <= ctx.eps or h <= ctx.eps:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_GEOMETRY,
                message=f"COCO bbox 非法: x={x}, y={y}, w={w}, h={h}",
                source_ref=source_ref,
            )
            continue

        confidence = 1.0
        if "score" in ann:
            try:
                confidence = float(ann["score"])
            except (TypeError, ValueError):
                fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_SCHEMA, message="annotation.score 非法", source_ref=source_ref)
                continue
            if not is_finite(confidence) or confidence < 0.0 or confidence > 1.0:
                fail_or_report(
                    ctx=ctx,
                    report=report,
                    code=ERR_CONVERT_SCHEMA,
                    message=f"annotation.score 越界: {confidence}",
                    source_ref=source_ref,
                )
                continue

        record = annotationirv1.AnnotationRecord(
            id=new_uuid(),
            sample_id=image_to_sample_id[image_id],
            label_id=category_to_label_id[category_id],
            source=annotationirv1.ANNOTATION_SOURCE_IMPORTED,
            confidence=confidence,
            geometry=annotationirv1.Geometry(rect=annotationirv1.RectGeometry(x=x, y=y, width=w, height=h)),
        )

        if ctx.include_external_ref:
            external = make_external_attrs(
                ann_key=str(ann.get("id") if ann.get("id") is not None else i),
                category_key=str(category_id),
                line=i,
            )
            record.attrs.CopyFrom(dict_to_struct({"external": external}))

        annotations.append(record)

    return build_batch(labels if ctx.emit_labels else None, samples, annotations)


def ir_to_coco(
    batch: annotationirv1.DataBatchIR,
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> dict[str, Any]:
    """将 DataBatchIR 转换为 COCO instances 字典。

    若需要读取 warnings/errors（strict=False 时），请由调用方传入 `report`。
    """

    report = make_report(report, strict=ctx.strict)

    labels_by_id, samples, anns = split_batch(batch, ctx=ctx, report=report)

    image_id_by_sample_id: dict[str, int] = {}
    sample_by_id: dict[str, annotationirv1.SampleRecord] = {}
    coco_images: list[dict[str, Any]] = []

    for i, sample in enumerate(samples, start=1):
        image_id_by_sample_id[sample.id] = i
        sample_by_id[sample.id] = sample
        meta = struct_to_dict(sample.meta) if sample.HasField("meta") else {}
        external = meta.get("external", {}) if isinstance(meta, dict) else {}
        if ctx.naming == "uuid":
            file_name = f"{sample.id}.jpg"
        else:
            file_name = str(external.get("file_name") or external.get("relpath") or f"{sample.id}.jpg")

        coco_images.append(
            {
                "id": i,
                "file_name": file_name,
                "width": int(sample.width),
                "height": int(sample.height),
            }
        )

    category_id_by_label_id: dict[str, int] = {}
    coco_categories: list[dict[str, Any]] = []

    def ensure_category(label_id: str) -> int:
        if label_id in category_id_by_label_id:
            return category_id_by_label_id[label_id]

        cat_id = len(category_id_by_label_id) + 1
        label = labels_by_id.get(label_id)
        name = label.name if label is not None and label.name else f"class_{cat_id}"
        category_id_by_label_id[label_id] = cat_id
        coco_categories.append({"id": cat_id, "name": name})
        return cat_id

    # 先把 labels 按 batch 顺序映射一遍，提升导出稳定性。
    for item in batch.items:
        if item.WhichOneof("item") == "label":
            ensure_category(item.label.id)

    coco_annotations: list[dict[str, Any]] = []
    ann_id = 1

    for idx, ann in enumerate(anns):
        source_ref = f"annotation[{idx}]"

        image_id = image_id_by_sample_id.get(ann.sample_id)
        if image_id is None:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"annotation.sample_id 不存在: {ann.sample_id}",
                source_ref=source_ref,
            )
            continue

        if not ann.HasField("geometry") or ann.geometry.WhichOneof("shape") != "rect":
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_UNSUPPORTED,
                message="COCO 导出仅支持 rect geometry",
                source_ref=source_ref,
            )
            continue

        sample = sample_by_id.get(ann.sample_id)
        if sample is None:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message=f"annotation.sample_id 不存在: {ann.sample_id}",
                source_ref=source_ref,
            )
            continue

        rect = ann.geometry.rect
        clipped = maybe_clip_rect(
            float(rect.x),
            float(rect.y),
            float(rect.width),
            float(rect.height),
            sample=sample,
            ctx=ctx,
            report=report,
            source_ref=source_ref,
        )
        if clipped is None:
            continue
        x, y, w, h = clipped

        coco_annotations.append(
            {
                "id": ann_id,
                "image_id": image_id,
                "category_id": ensure_category(ann.label_id),
                "bbox": [x, y, w, h],
                "area": w * h,
                "iscrowd": 0,
            }
        )
        ann_id += 1

    return {
        "images": coco_images,
        "categories": coco_categories,
        "annotations": coco_annotations,
    }
