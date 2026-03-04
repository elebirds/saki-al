from __future__ import annotations

"""DOTA dataset 级读写（Step 2）。"""

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
from saki_ir.convert.dota_obb import dota_txt_to_ir, ir_to_dota_txt
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def load_dota_dataset(
    root: str | Path,
    split: str = "train",
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """读取 DOTA 目录并转换为 IR。"""

    report = make_report(report, strict=ctx.strict)
    root_path = Path(root).resolve()
    split_name = str(split or "train").strip() or "train"

    resolved = _resolve_dota_dirs(root=root_path, split=split_name)
    if resolved is None:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_SCHEMA,
            message="未找到 DOTA 数据集目录（期望 train/images+train/labelTxt 或 images/labelTxt）",
            source_ref=str(root_path),
        )
        return build_batch(None, None, None)

    images_dir, labels_dir = resolved
    image_paths = [item for item in images_dir.rglob("*") if item.is_file() and item.suffix.lower() in _IMAGE_SUFFIXES]
    image_paths.sort()
    if ctx.max_samples is not None:
        image_paths = image_paths[: max(0, int(ctx.max_samples))]

    inner_ctx = replace(ctx, emit_labels=False)
    samples: list[annotationirv1.SampleRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    class_key_to_label_id: dict[str, str] = {}
    class_key_to_name: dict[str, str] = {}

    for image_path in image_paths:
        rel_from_root = _relative_to_root(root_path, image_path)
        txt_path = _label_path_for_image(image_path=image_path, images_dir=images_dir, labels_dir=labels_dir)

        if txt_path.exists():
            try:
                txt_text = txt_path.read_text(encoding="utf-8")
            except OSError as exc:
                fail_or_report(
                    ctx=ctx,
                    report=report,
                    code=ERR_CONVERT_IO,
                    message=f"读取 DOTA txt 失败: {exc}",
                    source_ref=str(txt_path),
                )
                txt_text = ""
        else:
            txt_text = ""

        image_w: int | None = None
        image_h: int | None = None
        if ctx.read_images:
            image_w, image_h = _read_image_size(image_path=image_path, ctx=ctx, report=report)

        per = dota_txt_to_ir(
            txt_text,
            image_w=image_w,
            image_h=image_h,
            class_names=None,
            image_relpath=rel_from_root,
            ctx=inner_ctx,
            report=report,
        )
        _, per_samples, per_annotations = split_batch(per, ctx=ctx, report=report, source_ref=f"{rel_from_root}:items")
        sample = require_single_sample(
            per_samples,
            ctx=ctx,
            report=report,
            source_ref=f"{rel_from_root}:samples",
            target_name="DOTA(load)",
        )
        if sample is None:
            continue
        samples.append(sample)

        for item_ann in per_annotations:
            if item_ann.sample_id != sample.id:
                fail_or_report(
                    ctx=ctx,
                    report=report,
                    code=ERR_CONVERT_SCHEMA,
                    message="annotation.sample_id 与 per-sample batch 的 sample.id 不一致",
                    source_ref=rel_from_root,
                )
                continue

            ann = annotationirv1.AnnotationRecord()
            ann.CopyFrom(item_ann)

            attrs = struct_to_dict(ann.attrs) if ann.HasField("attrs") else {}
            external = attrs.get("external", {}) if isinstance(attrs, dict) else {}
            category_key = str(external.get("category_key") or ann.label_id or "").strip()
            if not category_key:
                category_key = "unknown"

            label_id = class_key_to_label_id.get(category_key)
            if label_id is None:
                label_id = new_uuid()
                class_key_to_label_id[category_key] = label_id
                class_key_to_name[category_key] = category_key

            ann.label_id = label_id
            annotations.append(ann)

    labels: list[annotationirv1.LabelRecord] = []
    if ctx.emit_labels:
        for key, label_id in class_key_to_label_id.items():
            labels.append(annotationirv1.LabelRecord(id=label_id, name=class_key_to_name.get(key, key)))

    return build_batch(labels if ctx.emit_labels else None, samples, annotations)


def save_dota_dataset(
    batch: annotationirv1.DataBatchIR,
    root: str | Path,
    split: str = "train",
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> None:
    """将 IR 导出为 DOTA 目录结构（MMRotate 风格）。"""

    report = make_report(report, strict=ctx.strict)
    root_path = Path(root)
    split_name = str(split or "train").strip() or "train"
    images_dir = root_path / split_name / "images"
    labels_dir = root_path / split_name / "labelTxt"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    labels_by_id, samples, annotations = split_batch(batch, ctx=ctx, report=report)
    anns_by_sample: dict[str, list[annotationirv1.AnnotationRecord]] = {}
    for ann in annotations:
        anns_by_sample.setdefault(ann.sample_id, []).append(ann)

    for sample in samples:
        relpath = _sample_relpath(sample=sample, ctx=ctx)
        txt_rel = Path(relpath).with_suffix(".txt")
        txt_path = labels_dir / txt_rel
        sample_annotations = anns_by_sample.get(sample.id, [])

        labels: list[annotationirv1.LabelRecord] = []
        if ctx.emit_labels:
            used = {item.label_id for item in sample_annotations}
            for label_id in used:
                label = labels_by_id.get(label_id)
                if label is not None:
                    labels.append(label)

        sub = build_batch(labels if ctx.emit_labels else None, [sample], sample_annotations)
        txt = ir_to_dota_txt(sub, ctx=ctx, report=report)

        if not txt and sample_annotations:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="sample 含标注但导出结果为空",
                source_ref=f"sample:{sample.id}",
            )
            if not ctx.yolo_write_empty_label_files:
                continue
        if not txt and not ctx.yolo_write_empty_label_files:
            continue

        txt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            txt_path.write_text((txt + "\n") if txt else "", encoding="utf-8")
        except OSError as exc:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_IO,
                message=f"写入 DOTA txt 失败: {exc}",
                source_ref=str(txt_path),
            )


def _resolve_dota_dirs(*, root: Path, split: str) -> tuple[Path, Path] | None:
    candidates = [
        (root / split / "images", root / split / "labelTxt"),
        (root / "images" / split, root / "labelTxt" / split),
        (root / "images", root / "labelTxt"),
    ]
    for image_dir, label_dir in candidates:
        if image_dir.is_dir() and label_dir.is_dir():
            return image_dir.resolve(), label_dir.resolve()
    return None


def _label_path_for_image(*, image_path: Path, images_dir: Path, labels_dir: Path) -> Path:
    rel = image_path.relative_to(images_dir)
    return (labels_dir / rel).with_suffix(".txt")


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_image_size(
    *,
    image_path: Path,
    ctx: ConversionContext,
    report: ConversionReport,
) -> tuple[int | None, int | None]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message="未安装 pillow，无法读取 DOTA 图片尺寸",
            source_ref=str(image_path),
        )
        return None, None

    try:
        with Image.open(image_path) as img:
            return int(img.width), int(img.height)
    except OSError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"读取图片尺寸失败: {exc}",
            source_ref=str(image_path),
        )
        return None, None


def _sample_relpath(*, sample: annotationirv1.SampleRecord, ctx: ConversionContext) -> str:
    if ctx.naming == "keep_external" and sample.HasField("meta"):
        meta = struct_to_dict(sample.meta)
        external = meta.get("external", {}) if isinstance(meta, dict) else {}
        relpath = str(external.get("relpath") or external.get("file_name") or "")
        if relpath:
            return relpath
    return f"{sample.id}.png"

