from __future__ import annotations

"""Pascal VOC dataset 级读写（Step 2）。"""

from dataclasses import replace
from pathlib import Path

from saki_ir.convert.base import (
    ERR_CONVERT_IO,
    ERR_CONVERT_SCHEMA,
    ConversionContext,
    ConversionReport,
    build_batch,
    fail_or_report,
    make_report,
    new_uuid,
    require_single_sample,
    split_batch,
    struct_to_dict,
)
from saki_ir.convert.voc_det import ir_to_voc_xml, voc_xml_to_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1


def load_voc_dataset(
    root: str | Path,
    split: str,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """读取 VOC 目录并转换为 IR。"""

    report = make_report(report, strict=ctx.strict)
    root_path = Path(root)
    split_file = root_path / "ImageSets" / "Main" / f"{split}.txt"

    try:
        sample_keys = [line.strip() for line in split_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"读取 VOC split 文件失败: {exc}",
            source_ref=str(split_file),
        )
        return build_batch(None, None, None)

    if ctx.max_samples is not None:
        sample_keys = sample_keys[: max(0, int(ctx.max_samples))]

    inner_ctx = replace(ctx, emit_labels=False)
    samples: list[annotationirv1.SampleRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []

    label_key_to_id: dict[str, str] = {}
    label_key_to_name: dict[str, str] = {}

    for key in sample_keys:
        xml_path = root_path / "Annotations" / f"{key}.xml"
        try:
            xml_text = xml_path.read_text(encoding="utf-8")
        except OSError as exc:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_IO,
                message=f"读取 VOC XML 失败: {exc}",
                source_ref=str(xml_path),
            )
            continue

        per = voc_xml_to_ir(xml_text, image_relpath=f"JPEGImages/{key}.jpg", ctx=inner_ctx, report=report)
        _, per_samples, per_annotations = split_batch(per, ctx=ctx, report=report, source_ref=f"{xml_path}:items")
        per_sample = require_single_sample(
            per_samples,
            ctx=ctx,
            report=report,
            source_ref=f"{xml_path}:samples",
            target_name="VOC(load)",
        )
        if per_sample is None:
            continue
        samples.append(per_sample)

        for item_ann in per_annotations:
            if item_ann.sample_id != per_sample.id:
                fail_or_report(
                    ctx=ctx,
                    report=report,
                    code=ERR_CONVERT_SCHEMA,
                    message="annotation.sample_id 与 per-sample batch 的 sample.id 不一致",
                    source_ref=f"{xml_path}:annotation",
                )
                continue
            ann = annotationirv1.AnnotationRecord()
            ann.CopyFrom(item_ann)

            attrs = struct_to_dict(ann.attrs) if ann.HasField("attrs") else {}
            external = attrs.get("external", {}) if isinstance(attrs, dict) else {}
            category_key = str(external.get("category_key") or ann.label_id)
            if not category_key:
                category_key = "unknown"

            global_label_id = label_key_to_id.get(category_key)
            if global_label_id is None:
                global_label_id = new_uuid()
                label_key_to_id[category_key] = global_label_id
                label_key_to_name[category_key] = category_key

            ann.label_id = global_label_id
            annotations.append(ann)

    labels: list[annotationirv1.LabelRecord] = []
    if ctx.emit_labels:
        for key, lid in label_key_to_id.items():
            labels.append(annotationirv1.LabelRecord(id=lid, name=label_key_to_name.get(key, key)))

    return build_batch(labels if ctx.emit_labels else None, samples, annotations)


def save_voc_dataset(
    batch: annotationirv1.DataBatchIR,
    root: str | Path,
    split: str,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> None:
    """将 IR 导出为 VOC 目录结构。"""

    report = make_report(report, strict=ctx.strict)
    root_path = Path(root)
    ann_dir = root_path / "Annotations"
    set_dir = root_path / "ImageSets" / "Main"
    ann_dir.mkdir(parents=True, exist_ok=True)
    set_dir.mkdir(parents=True, exist_ok=True)

    labels_by_id, samples, annotations = split_batch(batch, ctx=ctx, report=report)
    anns_by_sample: dict[str, list[annotationirv1.AnnotationRecord]] = {}

    for ann in annotations:
        anns_by_sample.setdefault(ann.sample_id, []).append(ann)

    split_lines: list[str] = []

    for sample in samples:
        stem = _sample_stem(sample=sample, ctx=ctx)
        split_lines.append(stem)

        labels: list[annotationirv1.LabelRecord] = []
        annotations = anns_by_sample.get(sample.id, [])
        if ctx.emit_labels:
            used = {a.label_id for a in annotations}
            for lid in used:
                label = labels_by_id.get(lid)
                if label is not None:
                    labels.append(label)

        sub = build_batch(labels if ctx.emit_labels else None, [sample], annotations)
        xml_text = ir_to_voc_xml(sub, ctx=ctx, report=report)
        if not xml_text and not ctx.strict:
            continue

        out_xml = ann_dir / f"{stem}.xml"
        try:
            out_xml.write_text(xml_text, encoding="utf-8")
        except OSError as exc:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_IO,
                message=f"写入 VOC XML 失败: {exc}",
                source_ref=str(out_xml),
            )

    split_file = set_dir / f"{split}.txt"
    try:
        split_file.write_text("\n".join(split_lines) + ("\n" if split_lines else ""), encoding="utf-8")
    except OSError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"写入 VOC split 文件失败: {exc}",
            source_ref=str(split_file),
        )

def _sample_stem(*, sample: annotationirv1.SampleRecord, ctx: ConversionContext) -> str:
    if ctx.naming == "keep_external" and sample.HasField("meta"):
        meta = struct_to_dict(sample.meta)
        external = meta.get("external", {}) if isinstance(meta, dict) else {}
        relpath = str(external.get("relpath") or external.get("file_name") or "")
        if relpath:
            return Path(relpath).stem
    return sample.id
