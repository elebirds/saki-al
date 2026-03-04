from __future__ import annotations

"""Oriented R-CNN 数据准备流水线。

核心设计（必须读）：
1. 训练格式固定为 DOTA labelTxt，复用 saki-ir 的权威转换逻辑，
   避免在插件里重复实现几何转换。
2. 图片统一落盘为 PNG，保证 MMRotate DOTADataset 的 img_suffix 单值假设成立。
3. 同时输出 class_schema.json / dataset_manifest.json，
   用于训练可复现与问题排查。
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from saki_ir import ConversionContext, ConversionReport, save_dota_dataset
from saki_ir.convert.base import build_batch, split_batch
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb
from saki_plugin_sdk import WorkspaceProtocol, resolve_train_val_split

from saki_plugin_oriented_rcnn.common import sanitize_class_name, to_float, to_int
from saki_plugin_oriented_rcnn.types import PreparedDataset


@dataclass(frozen=True)
class _SampleAsset:
    sample_id: str
    source_path: Path


def prepare_dota_dataset(
    *,
    workspace: WorkspaceProtocol,
    labels: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    dataset_ir: irpb.DataBatchIR,
    splits: dict[str, list[dict[str, Any]]] | None,
    split_seed: int,
    val_ratio: float,
) -> PreparedDataset:
    data_root = workspace.data_dir

    # 关键约束：每次 prepare 都以“完整重建”方式执行，
    # 避免上轮残留文件污染本轮训练。
    if data_root.exists():
        shutil.rmtree(data_root, ignore_errors=True)
    data_root.mkdir(parents=True, exist_ok=True)

    train_images_dir = data_root / "train" / "images"
    val_images_dir = data_root / "val" / "images"
    train_images_dir.mkdir(parents=True, exist_ok=True)
    val_images_dir.mkdir(parents=True, exist_ok=True)

    labels_by_id, ir_samples, ir_annotations = split_batch(
        dataset_ir,
        ctx=ConversionContext(strict=False),
        report=ConversionReport(),
    )

    sample_assets = _collect_sample_assets(samples=samples)
    all_sample_ids = sorted(sample_assets.keys())

    train_ids, val_ids = _resolve_split(
        sample_ids=all_sample_ids,
        samples=samples,
        splits=splits,
        split_seed=split_seed,
        val_ratio=val_ratio,
    )

    val_degraded = len(val_ids) == 0
    if not train_ids:
        train_ids = set(all_sample_ids)
        val_ids = set()
        val_degraded = True

    safe_map = _build_safe_class_name_map(labels=labels, labels_by_id=labels_by_id)

    # 先拷贝图片，再导出标注，保证训练目录结构完整。
    _copy_images_as_png(
        sample_assets=sample_assets,
        train_ids=train_ids,
        val_ids=val_ids,
        train_images_dir=train_images_dir,
        val_images_dir=val_images_dir,
        val_degraded=val_degraded,
    )

    train_batch = _build_subset_batch(
        labels_by_id=labels_by_id,
        samples=ir_samples,
        annotations=ir_annotations,
        target_ids=train_ids,
        class_name_map=safe_map,
    )
    save_dota_dataset(
        train_batch,
        data_root,
        split="train",
        ctx=ConversionContext(
            strict=False,
            emit_labels=True,
            include_external_ref=False,
            naming="uuid",
            yolo_float_precision=6,
            yolo_write_empty_label_files=True,
        ),
        report=ConversionReport(),
    )

    if not val_degraded:
        val_batch = _build_subset_batch(
            labels_by_id=labels_by_id,
            samples=ir_samples,
            annotations=ir_annotations,
            target_ids=val_ids,
            class_name_map=safe_map,
        )
        save_dota_dataset(
            val_batch,
            data_root,
            split="val",
            ctx=ConversionContext(
                strict=False,
                emit_labels=True,
                include_external_ref=False,
                naming="uuid",
                yolo_float_precision=6,
                yolo_write_empty_label_files=True,
            ),
            report=ConversionReport(),
        )

    classes = tuple(_ordered_safe_class_names(labels=labels, safe_map=safe_map))
    manifest = {
        "sample_count": len(all_sample_ids),
        "train_sample_count": len(train_ids),
        "val_sample_count": 0 if val_degraded else len(val_ids),
        "annotation_count": sum(1 for item in ir_annotations if item.sample_id in (train_ids | val_ids)),
        "label_count": len(classes),
        "val_degraded": bool(val_degraded),
        "split_seed": int(split_seed),
        "val_split_ratio": float(val_ratio),
        "format": "dota",
        "image_suffix": "png",
    }

    (data_root / "class_schema.json").write_text(
        json.dumps(
            {
                "version": 1,
                "class_name_map": safe_map,
                "classes": list(classes),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return PreparedDataset(
        train_ids=set(train_ids),
        val_ids=set(val_ids),
        val_degraded=val_degraded,
        classes=classes,
        class_name_map=safe_map,
        manifest=manifest,
    )


def _collect_sample_assets(*, samples: list[dict[str, Any]]) -> dict[str, _SampleAsset]:
    assets: dict[str, _SampleAsset] = {}
    for row in samples:
        sample_id = str(row.get("id") or "").strip()
        path_raw = str(row.get("local_path") or "").strip()
        if not sample_id or not path_raw:
            continue
        src = Path(path_raw)
        if not src.exists() or not src.is_file():
            continue
        assets[sample_id] = _SampleAsset(sample_id=sample_id, source_path=src)
    return assets


def _resolve_split(
    *,
    sample_ids: list[str],
    samples: list[dict[str, Any]],
    splits: dict[str, list[dict[str, Any]]] | None,
    split_seed: int,
    val_ratio: float,
) -> tuple[set[str], set[str]]:
    known = set(sample_ids)
    train_ids: set[str] = set()
    val_ids: set[str] = set()

    # 优先使用 core 下发 split，保证与 orchestrator 一致。
    if isinstance(splits, dict):
        for item in splits.get("train") or []:
            if isinstance(item, dict):
                sample_id = str(item.get("id") or "").strip()
                if sample_id in known:
                    train_ids.add(sample_id)
        for item in splits.get("val") or []:
            if isinstance(item, dict):
                sample_id = str(item.get("id") or "").strip()
                if sample_id in known:
                    val_ids.add(sample_id)

    # 若未显式下发，则回退 sample 元数据 hint。
    if not train_ids and not val_ids:
        for item in samples:
            sample_id = str(item.get("id") or "").strip()
            if sample_id not in known:
                continue
            split_name = str(item.get("_split") or "").strip().lower()
            if split_name == "val":
                val_ids.add(sample_id)
            elif split_name == "train":
                train_ids.add(sample_id)

    # 最后兜底：确定性随机切分。
    if not train_ids and not val_ids:
        train_ids, val_ids, _ = resolve_train_val_split(
            sample_ids=sample_ids,
            split_seed=max(0, int(split_seed)),
            val_ratio=min(0.5, max(0.05, float(val_ratio))),
        )
    return train_ids, val_ids


def _build_safe_class_name_map(
    *,
    labels: list[dict[str, Any]],
    labels_by_id: dict[str, irpb.LabelRecord],
) -> dict[str, str]:
    """把 label_id -> 安全类名建立为确定性映射。

    设计约束：
    - 同名冲突通过追加序号去重，确保每个类名唯一。
    - 优先使用项目标签名称；若缺失则回退 IR 中的 label.name。
    """
    candidate_by_id: dict[str, str] = {}
    for row in labels:
        label_id = str(row.get("id") or "").strip()
        if not label_id:
            continue
        raw_name = str(row.get("name") or "").strip()
        if not raw_name and label_id in labels_by_id:
            raw_name = str(labels_by_id[label_id].name or "").strip()
        candidate_by_id[label_id] = sanitize_class_name(raw_name or label_id)

    # 补齐 dataset_ir 中存在但 labels 列表未带出的 label。
    for label_id, record in labels_by_id.items():
        if label_id in candidate_by_id:
            continue
        candidate_by_id[label_id] = sanitize_class_name(str(record.name or label_id))

    seen: dict[str, int] = {}
    final_map: dict[str, str] = {}
    for label_id in sorted(candidate_by_id.keys()):
        base = candidate_by_id[label_id]
        count = seen.get(base, 0)
        if count == 0:
            final = base
        else:
            final = f"{base}_{count + 1}"
        seen[base] = count + 1
        final_map[label_id] = final
    return final_map


def _ordered_safe_class_names(
    *,
    labels: list[dict[str, Any]],
    safe_map: dict[str, str],
) -> list[str]:
    """按项目标签顺序输出 class 列表，保证训练类别索引稳定。"""
    ordered: list[str] = []
    appended: set[str] = set()

    for row in labels:
        label_id = str(row.get("id") or "").strip()
        if not label_id:
            continue
        name = safe_map.get(label_id)
        if not name or name in appended:
            continue
        ordered.append(name)
        appended.add(name)

    for label_id in sorted(safe_map.keys()):
        name = safe_map[label_id]
        if name in appended:
            continue
        ordered.append(name)
        appended.add(name)

    return ordered


def _copy_images_as_png(
    *,
    sample_assets: dict[str, _SampleAsset],
    train_ids: set[str],
    val_ids: set[str],
    train_images_dir: Path,
    val_images_dir: Path,
    val_degraded: bool,
) -> None:
    for sample_id, item in sample_assets.items():
        # val_degraded 时，所有样本都写入 train。
        target_dir = train_images_dir
        if not val_degraded and sample_id in val_ids:
            target_dir = val_images_dir

        dst = target_dir / f"{sample_id}.png"

        # 强制转 PNG：
        # 1) 统一后缀，匹配 MMRotate 数据集读取行为。
        # 2) 消除源图像格式差异（jpg/tif/webp）带来的后续分支复杂度。
        with Image.open(item.source_path) as img:
            rgb = img.convert("RGB")
            rgb.save(dst, format="PNG")


def _build_subset_batch(
    *,
    labels_by_id: dict[str, irpb.LabelRecord],
    samples: list[irpb.SampleRecord],
    annotations: list[irpb.AnnotationRecord],
    target_ids: set[str],
    class_name_map: dict[str, str],
) -> irpb.DataBatchIR:
    target = {str(v) for v in target_ids}
    subset_samples: list[irpb.SampleRecord] = []
    subset_annotations: list[irpb.AnnotationRecord] = []
    used_label_ids: set[str] = set()

    for sample in samples:
        if sample.id in target:
            clone = irpb.SampleRecord()
            clone.CopyFrom(sample)
            # 让 save_dota_dataset 使用 sample.id 作为文件名。
            clone.ClearField("meta")
            subset_samples.append(clone)

    for ann in annotations:
        if ann.sample_id not in target:
            continue
        clone = irpb.AnnotationRecord()
        clone.CopyFrom(ann)
        # 关键点：把 label_id 替换为“安全类名”，
        # 这样 save_dota_dataset 在无 labels_by_id 命中时，会把 label_id 当类名输出。
        safe_name = class_name_map.get(str(ann.label_id), str(ann.label_id))
        clone.label_id = safe_name
        subset_annotations.append(clone)
        used_label_ids.add(str(ann.label_id))

    subset_labels: list[irpb.LabelRecord] = []
    for label_id in sorted(used_label_ids):
        safe_name = class_name_map.get(label_id, label_id)
        subset_labels.append(irpb.LabelRecord(id=safe_name, name=safe_name))

    return build_batch(subset_labels, subset_samples, subset_annotations)


def load_prepare_manifest(workspace: WorkspaceProtocol) -> dict[str, Any]:
    path = workspace.data_dir / "dataset_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_class_schema(workspace: WorkspaceProtocol) -> dict[str, Any]:
    path = workspace.data_dir / "class_schema.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def infer_image_hw(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        width, height = img.size
    return int(height), int(width)


def parse_split_params(splits: dict[str, Any] | None) -> tuple[int, float]:
    payload = splits if isinstance(splits, dict) else {}
    has_seed_key = "split_seed" in payload
    has_ratio_key = "val_split_ratio" in payload
    split_seed = max(0, to_int(payload.get("split_seed"), 0))
    val_ratio = min(0.5, max(0.05, to_float(payload.get("val_split_ratio"), 0.2)))

    # 兼容当前 executor 下发结构：
    # splits 里通常是 train/val 样本列表，split 参数写在每个样本的内部字段。
    # 这里做一次“从样本字段回捞”，避免读不到 split_seed/val_ratio 导致不一致。
    if (not has_seed_key) or (not has_ratio_key):
        for bucket in ("train", "val"):
            rows = payload.get(bucket)
            if not isinstance(rows, list):
                continue
            for item in rows:
                if not isinstance(item, dict):
                    continue
                if not has_seed_key:
                    split_seed = max(split_seed, max(0, to_int(item.get("_split_seed"), 0)))
                if not has_ratio_key:
                    val_ratio = min(0.5, max(0.05, to_float(item.get("_val_split_ratio"), 0.2)))
                if has_seed_key or split_seed > 0:
                    has_seed_key = True
                if has_ratio_key or val_ratio > 0.0:
                    has_ratio_key = True
                if has_seed_key and has_ratio_key:
                    break
            if has_seed_key and has_ratio_key:
                break

    return split_seed, val_ratio
