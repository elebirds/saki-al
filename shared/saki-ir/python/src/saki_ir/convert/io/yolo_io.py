from __future__ import annotations

"""YOLO dataset 级读写（Step 2）。"""

import ast
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

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
from saki_ir.convert.yolo_det import ir_to_yolo_txt, yolo_txt_to_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_yolo_dataset(
    root: Path,
    split: str,
    *,
    data_yaml: Path | None = None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """读取 YOLO 目录结构并转换为单个 DataBatchIR。"""

    report = make_report(report, strict=ctx.strict)
    root = Path(root)

    cfg: dict[str, Any] = {}
    yaml_path = data_yaml or (root / "data.yaml")
    if yaml_path.exists():
        cfg = _load_yaml_config(yaml_path=yaml_path, ctx=ctx, report=report)

    class_names = _extract_names(cfg.get("names"))

    split_rel = str(cfg.get(split) or f"images/{split}")
    images_dir = _resolve_images_dir(root=root, split_rel=split_rel, split=split)
    labels_dir = _resolve_labels_dir(root=root, split_rel=split_rel, split=split)

    image_paths = [p for p in images_dir.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES]
    image_paths.sort()

    if ctx.max_samples is not None:
        image_paths = image_paths[: max(0, int(ctx.max_samples))]

    inner_ctx = replace(ctx, emit_labels=False)

    samples: list[annotationirv1.SampleRecord] = []
    annotations: list[annotationirv1.AnnotationRecord] = []
    class_key_to_label_id: dict[str, str] = {}
    class_key_to_name: dict[str, str] = {}

    for image_path in image_paths:
        rel_from_root = _relative_to_root(root, image_path)
        rel_from_images = image_path.relative_to(images_dir)
        txt_path = (labels_dir / rel_from_images).with_suffix(".txt")

        if txt_path.exists():
            try:
                txt_text = txt_path.read_text(encoding="utf-8")
            except OSError as exc:
                fail_or_report(
                    ctx=ctx,
                    report=report,
                    code=ERR_CONVERT_IO,
                    message=f"读取 YOLO txt 失败: {exc}",
                    source_ref=str(txt_path),
                )
                txt_text = ""
        else:
            txt_text = ""

        image_w: int | None = None
        image_h: int | None = None
        if ctx.read_images:
            image_w, image_h = _read_image_size(image_path=image_path, ctx=ctx, report=report)

        per = yolo_txt_to_ir(
            txt_text,
            image_w=image_w,
            image_h=image_h,
            class_names=class_names,
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
            target_name="YOLO(load)",
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
            category_key = str(external.get("category_key") or ann.label_id)
            if not category_key:
                category_key = "unknown"

            lid = class_key_to_label_id.get(category_key)
            if lid is None:
                lid = new_uuid()
                class_key_to_label_id[category_key] = lid
                class_key_to_name[category_key] = _name_from_category_key(category_key, class_names)

            ann.label_id = lid
            annotations.append(ann)

    labels: list[annotationirv1.LabelRecord] = []
    if ctx.emit_labels:
        for key, lid in class_key_to_label_id.items():
            labels.append(annotationirv1.LabelRecord(id=lid, name=class_key_to_name.get(key, f"class_{key}")))

    return build_batch(labels if ctx.emit_labels else None, samples, annotations)


def save_yolo_dataset(
    batch: annotationirv1.DataBatchIR,
    root: Path,
    split: str,
    *,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> None:
    """将 IR 导出为 YOLO 目录结构（标签文件 + data.yaml）。"""

    report = make_report(report, strict=ctx.strict)
    root = Path(root)
    labels_dir = root / "labels" / split
    labels_dir.mkdir(parents=True, exist_ok=True)

    labels_by_id, samples, annotations = split_batch(batch, ctx=ctx, report=report)
    anns_by_sample: dict[str, list[annotationirv1.AnnotationRecord]] = {}
    for ann in annotations:
        anns_by_sample.setdefault(ann.sample_id, []).append(ann)

    class_to_index = _build_class_to_index(batch=batch, labels_by_id=labels_by_id)

    for sample in samples:
        if ctx.yolo_is_normalized and (sample.width <= 0 or sample.height <= 0):
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_SCHEMA,
                message="YOLO normalized 导出要求 sample.width/sample.height 为正整数",
                source_ref=f"sample:{sample.id}",
            )
            continue

        relpath = _sample_relpath(sample=sample, ctx=ctx)
        txt_rel = Path(relpath).with_suffix(".txt")
        txt_path = labels_dir / txt_rel
        sample_annotations = anns_by_sample.get(sample.id, [])

        sub = build_batch(
            list(labels_by_id.values()) if labels_by_id else None,
            [sample],
            sample_annotations,
        )
        txt = ir_to_yolo_txt(
            sub,
            image_w=int(sample.width),
            image_h=int(sample.height),
            class_to_index=class_to_index,
            ctx=ctx,
            report=report,
        )

        # 有标注但导出为空，视为导出失败（strict=False 时跳过当前文件）。
        if not txt and sample_annotations:
            continue

        txt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            txt_path.write_text((txt + "\n") if txt else "", encoding="utf-8")
        except OSError as exc:
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_IO,
                message=f"写入 YOLO txt 失败: {exc}",
                source_ref=str(txt_path),
            )

    data_yaml_path = root / "data.yaml"
    names_by_index = sorted(class_to_index.items(), key=lambda kv: kv[1])
    yaml_lines = [
        "path: .",
        f"{split}: images/{split}",
        "names:",
    ]
    for name, idx in names_by_index:
        yaml_lines.append(f"  {idx}: {name}")

    try:
        data_yaml_path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    except OSError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"写入 data.yaml 失败: {exc}",
            source_ref=str(data_yaml_path),
        )


def _load_yaml_config(*, yaml_path: Path, ctx: ConversionContext, report: ConversionReport) -> dict[str, Any]:
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"读取 data.yaml 失败: {exc}",
            source_ref=str(yaml_path),
        )
        return {}

    try:
        import yaml  # type: ignore
    except ImportError:
        report.warn("未安装 pyyaml，回退简化 YAML 解析，复杂 YAML 可能解析不完整")
        try:
            return _parse_simple_yaml(text)
        except Exception as exc:  # noqa: BLE001
            fail_or_report(
                ctx=ctx,
                report=report,
                code=ERR_CONVERT_IO,
                message=f"解析 data.yaml 失败: {exc}",
                source_ref=str(yaml_path),
            )
            return {}

    try:
        cfg = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message=f"解析 data.yaml 失败: {exc}",
            source_ref=str(yaml_path),
        )
        return {}

    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        fail_or_report(
            ctx=ctx,
            report=report,
            code=ERR_CONVERT_IO,
            message="data.yaml 顶层必须是映射对象",
            source_ref=str(yaml_path),
        )
        return {}

    return dict(cfg)


def _resolve_images_dir(*, root: Path, split_rel: str, split: str) -> Path:
    split_path = Path(split_rel)
    images_dir = split_path.resolve() if split_path.is_absolute() else (root / split_path).resolve()
    if images_dir.exists():
        return images_dir
    return (root / "images" / split).resolve()


def _resolve_labels_dir(*, root: Path, split_rel: str, split: str) -> Path:
    split_path = Path(split_rel)
    split_abs = split_path.resolve() if split_path.is_absolute() else (root / split_path).resolve()

    parts = list(split_abs.parts)
    if "images" in parts:
        idx = len(parts) - 1 - parts[::-1].index("images")
        parts[idx] = "labels"
        return Path(*parts).resolve()

    return (root / "labels" / split).resolve()


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}

    if text.startswith("{"):
        return json.loads(text)

    lines = text.splitlines()
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        if key != "names":
            out[key] = _strip_quotes(value)
            continue

        if value:
            if value.startswith("["):
                parsed = ast.literal_eval(value)
                out["names"] = [str(v) for v in parsed]
            else:
                out["names"] = _strip_quotes(value)
            continue

        names_dict: dict[str, str] = {}
        names_list: list[str] = []

        while i < len(lines):
            blk = lines[i]
            if not blk.strip():
                i += 1
                continue
            if not blk.startswith(" ") and not blk.startswith("\t"):
                break

            content = blk.strip()
            i += 1
            if content.startswith("-"):
                names_list.append(_strip_quotes(content[1:].strip()))
                continue
            if ":" in content:
                k, v = content.split(":", 1)
                names_dict[_strip_quotes(k.strip())] = _strip_quotes(v.strip())

        if names_dict:
            out["names"] = names_dict
        elif names_list:
            out["names"] = names_list

    return out


def _extract_names(names_obj: Any) -> list[str] | None:
    if names_obj is None:
        return None
    if isinstance(names_obj, list):
        return [str(v) for v in names_obj]
    if isinstance(names_obj, dict):
        ordered = sorted(names_obj.items(), key=lambda kv: int(kv[0]))
        return [str(v) for _, v in ordered]
    return None


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    return v


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
            message="未安装 pillow，无法读取 YOLO 图片尺寸",
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


def _name_from_category_key(category_key: str, class_names: list[str] | None) -> str:
    if category_key.isdigit() and class_names is not None:
        idx = int(category_key)
        if 0 <= idx < len(class_names):
            return str(class_names[idx])
    return f"class_{category_key}"


def _sample_relpath(*, sample: annotationirv1.SampleRecord, ctx: ConversionContext) -> str:
    if ctx.naming == "keep_external" and sample.HasField("meta"):
        meta = struct_to_dict(sample.meta)
        external = meta.get("external", {}) if isinstance(meta, dict) else {}
        relpath = str(external.get("relpath") or external.get("file_name") or "")
        if relpath:
            return relpath
    return f"{sample.id}.jpg"


def _build_class_to_index(
    *,
    batch: annotationirv1.DataBatchIR,
    labels_by_id: dict[str, annotationirv1.LabelRecord],
) -> dict[str, int]:
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
        label = labels_by_id.get(ann.label_id)
        name = label.name if label is not None and label.name else ann.label_id
        if name not in out:
            out[name] = next_idx
            next_idx += 1

    return out
