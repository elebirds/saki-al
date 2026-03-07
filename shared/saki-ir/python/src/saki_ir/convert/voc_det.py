from __future__ import annotations

"""Pascal VOC detection <-> saki-ir 转换（Step 1，纯语义层）。"""

from pathlib import Path
from xml.etree import ElementTree as ET

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
    require_single_sample,
    split_batch,
    struct_to_dict,
    tlbr_to_tlwh,
    tlwh_to_tlbr,
)


def voc_xml_to_ir(
    xml_text: str,
    *,
    image_relpath: str | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """将单个 VOC XML 文本转换为 DataBatchIR。"""

    report = make_report(report, strict=ctx.strict)

    if ctx.voc_coord_base not in (0, 1):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"voc_coord_base 仅支持 0 或 1，当前为 {ctx.voc_coord_base}",
            source_ref="voc_coord_base",
        )

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"VOC XML 解析失败: {exc}",
            source_ref="xml",
        )
        return build_batch(None, None, None)

    filename = (root.findtext("filename") or "").strip()
    width_text = (root.findtext("size/width") or "").strip()
    height_text = (root.findtext("size/height") or "").strip()

    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="VOC size/width 或 size/height 非法",
            source_ref="size",
        )
        width = 0
        height = 0

    sample_id = new_uuid()
    sample = annotationirv1.SampleRecord(id=sample_id, width=width, height=height)

    relpath = image_relpath or filename or f"{sample_id}.jpg"
    if ctx.include_external_ref:
        sample.meta.CopyFrom(
            dict_to_struct(
                {
                    "external": make_external_meta(
                        source="voc",
                        sample_key=filename or Path(relpath).stem,
                        file_name=filename or Path(relpath).name,
                        relpath=relpath,
                    )
                }
            )
        )

    labels: list[annotationirv1.LabelRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    label_name_to_id: dict[str, str] = {}

    for line_no, obj in enumerate(root.findall("object"), start=1):
        source_ref = f"object[{line_no}]"
        name = (obj.findtext("name") or "").strip() or "unknown"
        bnd = obj.find("bndbox")
        if bnd is None:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="VOC object 缺失 bndbox",
                source_ref=source_ref,
            )
            continue

        try:
            xmin = float((bnd.findtext("xmin") or "").strip())
            ymin = float((bnd.findtext("ymin") or "").strip())
            xmax = float((bnd.findtext("xmax") or "").strip())
            ymax = float((bnd.findtext("ymax") or "").strip())
        except ValueError:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="VOC bndbox 坐标非法",
                source_ref=source_ref,
            )
            continue

        if ctx.voc_coord_base == 1:
            xmin -= 1.0
            ymin -= 1.0
            xmax -= 1.0
            ymax -= 1.0

        x, y, w, h = tlbr_to_tlwh(xmin, ymin, xmax, ymax)
        if not is_finite(x, y, w, h) or w <= ctx.eps or h <= ctx.eps:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_GEOMETRY,
                message=f"VOC 框非法: x={x}, y={y}, w={w}, h={h}",
                source_ref=source_ref,
            )
            continue

        label_id = label_name_to_id.get(name)
        if label_id is None:
            label_id = new_uuid()
            label_name_to_id[name] = label_id
            if ctx.emit_labels:
                labels.append(annotationirv1.LabelRecord(id=label_id, name=name))

        ann = annotationirv1.AnnotationRecord(
            id=new_uuid(),
            sample_id=sample_id,
            label_id=label_id,
            source=annotationirv1.ANNOTATION_SOURCE_IMPORTED,
            confidence=1.0,
            geometry=annotationirv1.Geometry(rect=annotationirv1.RectGeometry(x=x, y=y, width=w, height=h)),
        )

        if ctx.include_external_ref:
            ann.attrs.CopyFrom(
                dict_to_struct(
                    {
                        "external": make_external_attrs(
                            ann_key=f"{name}:{line_no}",
                            category_key=name,
                            line=line_no,
                        )
                    }
                )
            )

        annotations.append(ann)

    return build_batch(labels if ctx.emit_labels else None, [sample], annotations)


def ir_to_voc_xml(
    batch: annotationirv1.DataBatchIR,
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> str:
    """将 DataBatchIR（单 sample）导出为 VOC XML 文本。

    若需要读取 warnings/errors（strict=False 时），请由调用方传入 `report`。
    """

    report = make_report(report, strict=ctx.strict)

    if ctx.voc_coord_base not in (0, 1):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message=f"voc_coord_base 仅支持 0 或 1，当前为 {ctx.voc_coord_base}",
            source_ref="voc_coord_base",
        )
        return ""

    labels_by_id, samples, anns = split_batch(batch, ctx=ctx, report=report)
    sample = require_single_sample(
        samples,
        ctx=ctx,
        report=report,
        source_ref="batch.samples",
        target_name="VOC",
    )
    if sample is None:
        return ""
    sample_meta = struct_to_dict(sample.meta) if sample.HasField("meta") else {}
    sample_external = sample_meta.get("external", {}) if isinstance(sample_meta, dict) else {}
    relpath = str(sample_external.get("relpath") or sample_external.get("file_name") or f"{sample.id}.jpg")
    file_name = Path(relpath).name

    root = ET.Element("annotation")
    ET.SubElement(root, "filename").text = file_name

    path_text = sample_external.get("relpath")
    if path_text:
        ET.SubElement(root, "path").text = str(path_text)

    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(int(sample.width))
    ET.SubElement(size, "height").text = str(int(sample.height))
    ET.SubElement(size, "depth").text = "3"

    for idx, ann in enumerate(anns):
        source_ref = f"annotation[{idx}]"
        if ann.sample_id != sample.id:
            continue

        if not ann.HasField("geometry") or ann.geometry.WhichOneof("shape") != "rect":
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_UNSUPPORTED,
                message="VOC 导出仅支持 rect geometry",
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

        xmin, ymin, xmax, ymax = tlwh_to_tlbr(x, y, w, h)
        if ctx.voc_coord_base == 1:
            xmin += 1.0
            ymin += 1.0
            xmax += 1.0
            ymax += 1.0

        obj = ET.SubElement(root, "object")
        label = labels_by_id.get(ann.label_id)
        ET.SubElement(obj, "name").text = label.name if label is not None and label.name else ann.label_id
        bnd = ET.SubElement(obj, "bndbox")
        ET.SubElement(bnd, "xmin").text = _fmt_voc_number(xmin)
        ET.SubElement(bnd, "ymin").text = _fmt_voc_number(ymin)
        ET.SubElement(bnd, "xmax").text = _fmt_voc_number(xmax)
        ET.SubElement(bnd, "ymax").text = _fmt_voc_number(ymax)

    return ET.tostring(root, encoding="unicode")


def _fmt_voc_number(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.6f}".rstrip("0").rstrip(".")
