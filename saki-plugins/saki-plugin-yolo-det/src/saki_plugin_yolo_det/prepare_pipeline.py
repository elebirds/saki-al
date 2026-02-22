from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from saki_plugin_yolo_det.split_policy import resolve_train_val_split
from saki_plugin_yolo_det.types import PreparedDataset
from saki_plugin_sdk import Workspace
from saki_ir import ConversionContext, ConversionReport, save_yolo_dataset
from saki_ir.convert.base import build_batch, split_batch
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


@dataclass(frozen=True)
class IRLabelWriteStats:
    annotation_count: int
    error_count: int
    warning_count: int


# yolo_task → saki-ir label format mapping
_YOLO_TASK_FORMAT_MAP: dict[str, str] = {
    "detect": "det",
    "obb": "obb_poly8",
}


def prepare_yolo_dataset(
    *,
    workspace: Workspace,
    labels: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    infer_image_hw: Callable[[Path], tuple[int, int]],
    to_int: Callable[[Any, int], int],
    dataset_ir: irpb.DataBatchIR,
    splits: dict[str, list[dict[str, Any]]] | None = None,
    yolo_task: str = "obb",
) -> PreparedDataset:
    data_root = workspace.data_dir
    images_train_dir = data_root / "images" / "train"
    images_val_dir = data_root / "images" / "val"
    labels_train_dir = data_root / "labels" / "train"
    labels_val_dir = data_root / "labels" / "val"
    images_train_dir.mkdir(parents=True, exist_ok=True)
    images_val_dir.mkdir(parents=True, exist_ok=True)
    labels_train_dir.mkdir(parents=True, exist_ok=True)
    labels_val_dir.mkdir(parents=True, exist_ok=True)

    _label_id_to_idx, names = _build_label_index(labels)
    sample_map = _build_sample_map(
        samples=samples,
        to_int=to_int,
        infer_image_hw=infer_image_hw,
    )

    sample_ids = sorted(sample_map.keys())
    split_seed = max(0, to_int((splits or {}).get("split_seed"), 0))
    val_ratio_raw = (splits or {}).get("val_split_ratio")
    try:
        val_ratio = float(val_ratio_raw) if val_ratio_raw is not None else 0.2
    except Exception:
        val_ratio = 0.2

    train_ids, val_ids = _resolve_split_from_core(
        sample_ids=sample_ids,
        samples=samples,
        splits=splits,
    )
    val_degraded = len(val_ids) == 0
    if len(train_ids) == 0:
        train_ids = set(sample_ids)
        val_ids = set()
        val_degraded = True
    if len(train_ids) > 0 and len(val_ids) > 0:
        val_degraded = False

    if len(train_ids) == len(sample_ids) and len(val_ids) == 0 and split_seed > 0:
        # 兜底：若 core 未下发 split，可按种子再切一次。
        train_ids, val_ids, val_degraded = resolve_train_val_split(
            sample_ids=sample_ids,
            split_seed=split_seed,
            val_ratio=val_ratio,
        )
    label_stats = _write_dataset_files(
        sample_map=sample_map,
        train_ids=train_ids,
        val_ids=val_ids,
        val_degraded=val_degraded,
        images_train_dir=images_train_dir,
        images_val_dir=images_val_dir,
        labels_train_dir=labels_train_dir,
        labels_val_dir=labels_val_dir,
        data_root=data_root,
        dataset_ir=dataset_ir,
        yolo_task=yolo_task,
    )

    _write_dataset_yaml(
        data_root=data_root,
        names=names,
        val_degraded=val_degraded,
        split_seed=split_seed,
    )
    manifest = _build_manifest(
        sample_count=len(sample_map),
        train_sample_count=len(train_ids),
        val_sample_count=len(val_ids),
        annotation_count=label_stats.annotation_count,
        label_count=len(names),
        invalid_label_count=label_stats.error_count,
        skipped_annotation_count=label_stats.warning_count,
        val_degraded=val_degraded,
        split_seed=split_seed,
        val_split_ratio=val_ratio,
    )
    (data_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return PreparedDataset(manifest=manifest, yolo_task=yolo_task)


def _resolve_split_from_core(
    *,
    sample_ids: list[str],
    samples: list[dict[str, Any]],
    splits: dict[str, list[dict[str, Any]]] | None,
) -> tuple[set[str], set[str]]:
    known = set(sample_ids)
    train_ids: set[str] = set()
    val_ids: set[str] = set()

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

    if not train_ids and not val_ids:
        for item in samples:
            sample_id = str(item.get("id") or "").strip()
            if sample_id not in known:
                continue
            split = str(item.get("_split") or "").strip().lower()
            if split == "val":
                val_ids.add(sample_id)
            elif split == "train":
                train_ids.add(sample_id)

    if not train_ids and not val_ids:
        train_ids = set(sample_ids)

    return train_ids, val_ids


def _build_label_index(labels: list[dict[str, Any]]) -> tuple[dict[str, int], dict[int, str]]:
    label_id_to_idx: dict[str, int] = {}
    names: dict[int, str] = {}
    for idx, item in enumerate(labels):
        label_id = str(item.get("id") or "")
        if not label_id:
            continue
        label_id_to_idx[label_id] = idx
        names[idx] = str(item.get("name") or f"class_{idx}")
    return label_id_to_idx, names


def _build_sample_map(
    samples: list[dict[str, Any]],
    *,
    to_int: Callable[[Any, int], int],
    infer_image_hw: Callable[[Path], tuple[int, int]],
) -> dict[str, dict[str, Any]]:
    sample_map: dict[str, dict[str, Any]] = {}
    for sample in samples:
        sample_id = str(sample.get("id") or "")
        local_path_raw = str(sample.get("local_path") or "")
        if not sample_id or not local_path_raw:
            continue
        src = Path(local_path_raw)
        if not src.exists():
            continue

        width = to_int(sample.get("width"), 0)
        height = to_int(sample.get("height"), 0)
        if width <= 0 or height <= 0:
            try:
                inferred_h, inferred_w = infer_image_hw(src)
                width = int(inferred_w)
                height = int(inferred_h)
            except Exception:
                width = max(0, width)
                height = max(0, height)

        sample_map[sample_id] = {
            "source_path": src,
            "width": width,
            "height": height,
        }
    return sample_map


def _write_dataset_files(
    *,
    sample_map: dict[str, dict[str, Any]],
    train_ids: set[str],
    val_ids: set[str],
    val_degraded: bool,
    images_train_dir: Path,
    images_val_dir: Path,
    labels_train_dir: Path,
    labels_val_dir: Path,
    data_root: Path,
    dataset_ir: irpb.DataBatchIR,
    yolo_task: str = "obb",
) -> IRLabelWriteStats:
    for sample_id, item in sample_map.items():
        target_images_dir = images_train_dir
        if not val_degraded and sample_id in val_ids:
            target_images_dir = images_val_dir
        src = Path(item["source_path"])
        dst = target_images_dir / f"{sample_id}.jpg"
        shutil.copy2(src, dst)

    shutil.rmtree(labels_train_dir, ignore_errors=True)
    labels_train_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(labels_val_dir, ignore_errors=True)
    labels_val_dir.mkdir(parents=True, exist_ok=True)

    return _write_label_files_with_ir(
        data_root=data_root,
        dataset_ir=dataset_ir,
        train_ids=train_ids,
        val_ids=val_ids,
        val_degraded=val_degraded,
        yolo_task=yolo_task,
    )


def _write_label_files_with_ir(
    *,
    data_root: Path,
    dataset_ir: irpb.DataBatchIR,
    train_ids: set[str],
    val_ids: set[str],
    val_degraded: bool,
    yolo_task: str = "obb",
) -> IRLabelWriteStats:
    yolo_label_format = _YOLO_TASK_FORMAT_MAP.get(yolo_task, "obb_poly8")
    ctx = ConversionContext(
        strict=False,
        include_external_ref=False,
        emit_labels=True,
        yolo_is_normalized=True,
        yolo_label_format=yolo_label_format,
        yolo_obb_angle_unit="deg",
        yolo_write_empty_label_files=True,
        naming="uuid",
        read_images=False,
    )
    report = ConversionReport()
    labels_by_id, samples, annotations = split_batch(dataset_ir, ctx=ctx, report=report)
    label_records = list(labels_by_id.values())

    train_batch = _subset_ir_batch(
        labels=label_records,
        samples=samples,
        annotations=annotations,
        target_sample_ids=train_ids,
    )
    save_yolo_dataset(
        batch=train_batch,
        root=data_root,
        split="train",
        ctx=ctx,
        report=report,
    )

    selected_sample_ids = set(train_ids)
    if not val_degraded:
        selected_sample_ids |= set(val_ids)
        val_batch = _subset_ir_batch(
            labels=label_records,
            samples=samples,
            annotations=annotations,
            target_sample_ids=val_ids,
        )
        save_yolo_dataset(
            batch=val_batch,
            root=data_root,
            split="val",
            ctx=ctx,
            report=report,
        )

    if report.errors:
        preview = "; ".join(report.errors[:3])
        raise RuntimeError(f"saki-ir yolo label export failed: {preview}")

    annotation_count = sum(1 for item in annotations if item.sample_id in selected_sample_ids)
    return IRLabelWriteStats(
        annotation_count=annotation_count,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
    )


def _subset_ir_batch(
    *,
    labels: list[irpb.LabelRecord],
    samples: list[irpb.SampleRecord],
    annotations: list[irpb.AnnotationRecord],
    target_sample_ids: set[str],
) -> irpb.DataBatchIR:
    selected_sample_ids = {str(item) for item in target_sample_ids}
    subset_samples = [item for item in samples if item.id in selected_sample_ids]
    subset_annotations = [item for item in annotations if item.sample_id in selected_sample_ids]
    return build_batch(labels, subset_samples, subset_annotations)


def _write_dataset_yaml(
    *,
    data_root: Path,
    names: dict[int, str],
    val_degraded: bool,
    split_seed: int,
) -> None:
    dataset_yaml = {
        "path": str(data_root.resolve()),
        "train": "images/train",
        "val": "images/train" if val_degraded else "images/val",
        "names": names,
        "val_degraded": val_degraded,
        "split_seed": split_seed,
    }
    (data_root / "dataset.yaml").write_text(
        json.dumps(dataset_yaml, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_manifest(
    *,
    sample_count: int,
    train_sample_count: int,
    val_sample_count: int,
    annotation_count: int,
    label_count: int,
    invalid_label_count: int,
    skipped_annotation_count: int,
    val_degraded: bool,
    split_seed: int,
    val_split_ratio: float,
) -> dict[str, Any]:
    return {
        "sample_count": sample_count,
        "train_sample_count": train_sample_count,
        "val_sample_count": 0 if val_degraded else val_sample_count,
        "annotation_count": annotation_count,
        "label_count": label_count,
        "invalid_label_count": invalid_label_count,
        "skipped_annotation_count": skipped_annotation_count,
        "val_degraded": val_degraded,
        "split_seed": split_seed,
        "val_split_ratio": val_split_ratio,
    }
