from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from saki_executor.jobs.workspace import Workspace
from saki_executor.plugins.builtin.yolo_det.split_policy import resolve_train_val_split
from saki_executor.plugins.builtin.yolo_det.types import PreparedDataset


def prepare_yolo_dataset(
    *,
    workspace: Workspace,
    labels: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    infer_image_hw: Callable[[Path], tuple[int, int]],
    to_int: Callable[[Any, int], int],
    annotation_to_line: Callable[..., str | None],
    resolve_split_config: Callable[[Workspace], tuple[int, float]],
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

    label_id_to_idx, names = _build_label_index(labels)
    sample_map = _build_sample_map(samples, to_int=to_int)
    ann_by_sample, skipped_count, invalid_label_count = _build_annotations_by_sample(
        annotations=annotations,
        sample_map=sample_map,
        label_id_to_idx=label_id_to_idx,
        infer_image_hw=infer_image_hw,
        annotation_to_line=annotation_to_line,
    )

    sample_ids = sorted(sample_map.keys())
    split_seed, val_ratio = resolve_split_config(workspace)
    train_ids, val_ids, val_degraded = resolve_train_val_split(
        sample_ids=sample_ids,
        split_seed=split_seed,
        val_ratio=val_ratio,
    )
    _write_dataset_files(
        sample_map=sample_map,
        ann_by_sample=ann_by_sample,
        train_ids=train_ids,
        val_ids=val_ids,
        val_degraded=val_degraded,
        images_train_dir=images_train_dir,
        images_val_dir=images_val_dir,
        labels_train_dir=labels_train_dir,
        labels_val_dir=labels_val_dir,
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
        annotation_count=sum(len(v) for v in ann_by_sample.values()),
        label_count=len(names),
        invalid_label_count=invalid_label_count,
        skipped_annotation_count=skipped_count,
        val_degraded=val_degraded,
        split_seed=split_seed,
        val_split_ratio=val_ratio,
    )
    (data_root / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return PreparedDataset(manifest=manifest)


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
        sample_map[sample_id] = {
            "source_path": src,
            "width": to_int(sample.get("width"), 0),
            "height": to_int(sample.get("height"), 0),
        }
    return sample_map


def _build_annotations_by_sample(
    *,
    annotations: list[dict[str, Any]],
    sample_map: dict[str, dict[str, Any]],
    label_id_to_idx: dict[str, int],
    infer_image_hw: Callable[[Path], tuple[int, int]],
    annotation_to_line: Callable[..., str | None],
) -> tuple[dict[str, list[str]], int, int]:
    ann_by_sample: dict[str, list[str]] = {}
    skipped_count = 0
    invalid_label_count = 0
    for ann in annotations:
        sample_id = str(ann.get("sample_id") or "")
        category_id = str(ann.get("category_id") or "")
        if sample_id not in sample_map or category_id not in label_id_to_idx:
            skipped_count += 1
            continue
        item = sample_map[sample_id]
        h = int(item["height"] or 0)
        w = int(item["width"] or 0)
        if h <= 0 or w <= 0:
            try:
                h, w = infer_image_hw(Path(item["source_path"]))
            except Exception:
                skipped_count += 1
                continue
        line = annotation_to_line(
            ann=ann,
            cls_idx=label_id_to_idx[category_id],
            width=w,
            height=h,
        )
        if not line:
            invalid_label_count += 1
            continue
        ann_by_sample.setdefault(sample_id, []).append(line)
    return ann_by_sample, skipped_count, invalid_label_count


def _write_dataset_files(
    *,
    sample_map: dict[str, dict[str, Any]],
    ann_by_sample: dict[str, list[str]],
    train_ids: set[str],
    val_ids: set[str],
    val_degraded: bool,
    images_train_dir: Path,
    images_val_dir: Path,
    labels_train_dir: Path,
    labels_val_dir: Path,
) -> None:
    for sample_id, item in sample_map.items():
        target_images_dir = images_train_dir
        target_labels_dir = labels_train_dir
        if not val_degraded and sample_id in val_ids:
            target_images_dir = images_val_dir
            target_labels_dir = labels_val_dir
        src = Path(item["source_path"])
        dst = target_images_dir / f"{sample_id}.jpg"
        shutil.copy2(src, dst)
        label_file = target_labels_dir / f"{sample_id}.txt"
        label_file.write_text("\n".join(ann_by_sample.get(sample_id, [])), encoding="utf-8")


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

