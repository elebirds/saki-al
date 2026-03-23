from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from typing import Iterable


@dataclass(frozen=True)
class SampleRecord:
    sample_id: str
    stem: str
    image_path: Path
    ann_path: Path
    class_names: tuple[str, ...]
    instance_count: int
    is_negative: bool
    class_mask: str
    instance_count_bucket: str


@dataclass(frozen=True)
class SplitBundle:
    dataset_name: str
    manifest: dict[str, object]
    summary: dict[str, object]


def scan_dota_export(dota_root: Path, class_names: tuple[str, ...]) -> list[SampleRecord]:
    ann_dir = dota_root / "train" / "labelTxt"
    image_dir = dota_root / "train" / "images"
    records: list[SampleRecord] = []

    for ann_path in sorted(ann_dir.glob("*.txt")):
        stem = ann_path.stem
        image_path = _resolve_image_path(image_dir, stem)
        instance_labels = _parse_dota_labels(ann_path)
        instance_count = len(instance_labels)
        is_negative = instance_count == 0
        class_mask = _build_class_mask(instance_labels, class_names)
        instance_count_bucket = _bucket_instance_count(instance_count)

        records.append(
            SampleRecord(
                sample_id=stem,
                stem=stem,
                image_path=image_path,
                ann_path=ann_path,
                class_names=class_names,
                instance_count=instance_count,
                is_negative=is_negative,
                class_mask=class_mask,
                instance_count_bucket=instance_count_bucket,
            )
        )

    return sorted(records, key=lambda record: record.stem)


def resolve_fallback_level(
    *,
    strict_key: str,
    class_key: str,
    neg_key: str,
    strict_counts: dict[str, int],
    class_counts: dict[str, int],
    neg_counts: dict[str, int],
) -> int:
    if strict_counts.get(strict_key, 0) >= 3:
        return 0
    if class_counts.get(class_key, 0) >= 3:
        return 1
    if neg_counts.get(neg_key, 0) >= 3:
        return 2
    return 2


def generate_split_bundle(
    sample_inventory: list[SampleRecord],
    *,
    dataset_name: str,
    holdout_seed: int,
    split_seeds: list[int],
    test_ratio: float,
    val_ratio: float,
) -> SplitBundle:
    sample_ids = [record.sample_id for record in sorted(sample_inventory, key=lambda r: r.sample_id)]
    test_ids, remaining_ids = _split_holdout(sample_ids, holdout_seed, test_ratio)
    split_manifest: dict[str, dict[str, list[str]]] = {}
    split_summary: dict[str, dict[str, object]] = {}
    record_lookup = {record.sample_id: record for record in sample_inventory}
    val_ratio_trainval = _normalize_val_ratio(test_ratio, val_ratio)

    for seed in split_seeds:
        train_ids, val_ids = _split_train_val(remaining_ids, seed, val_ratio_trainval)
        split_manifest[str(seed)] = {
            "train_ids": train_ids,
            "val_ids": val_ids,
            "test_ids": test_ids,
        }
        split_summary[str(seed)] = _build_split_summary(
            train_ids=train_ids,
            val_ids=val_ids,
            test_ids=test_ids,
            record_lookup=record_lookup,
        )

    manifest: dict[str, object] = {
        "dataset_name": dataset_name,
        "holdout_seed": holdout_seed,
        "test_ratio": test_ratio,
        "val_ratio": val_ratio,
        "split_seeds": split_seeds,
        "splits": split_manifest,
    }
    summary: dict[str, object] = {
        "dataset_name": dataset_name,
        "split_count": len(split_seeds),
        "splits": split_summary,
    }
    return SplitBundle(dataset_name=dataset_name, manifest=manifest, summary=summary)


def _resolve_image_path(image_dir: Path, stem: str) -> Path:
    candidates = sorted(image_dir.glob(f"{stem}.*"))
    if candidates:
        return candidates[0]
    return image_dir / f"{stem}.png"


def _parse_dota_labels(ann_path: Path) -> list[str]:
    labels: list[str] = []
    for line in ann_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("imagesource:") or lower.startswith("gsd:"):
            continue
        parts = stripped.split()
        if len(parts) < 9:
            continue
        labels.append(parts[8])
    return labels


def _build_class_mask(labels: Iterable[str], class_names: tuple[str, ...]) -> str:
    label_set = set(labels)
    return "".join("1" if name in label_set else "0" for name in class_names)


def _bucket_instance_count(instance_count: int) -> str:
    if instance_count <= 0:
        return "0"
    if instance_count == 1:
        return "1"
    if instance_count <= 4:
        return "2-4"
    return ">=5"


def _split_holdout(
    sample_ids: list[str],
    holdout_seed: int,
    test_ratio: float,
) -> tuple[list[str], list[str]]:
    rng = random.Random(holdout_seed)
    shuffled = list(sample_ids)
    rng.shuffle(shuffled)
    test_count = round(len(shuffled) * test_ratio)
    test_ids = sorted(shuffled[:test_count])
    remaining_ids = sorted(shuffled[test_count:])
    return test_ids, remaining_ids


def _split_train_val(
    remaining_ids: list[str],
    split_seed: int,
    val_ratio_trainval: float,
) -> tuple[list[str], list[str]]:
    rng = random.Random(split_seed)
    shuffled = list(remaining_ids)
    rng.shuffle(shuffled)
    val_count = round(len(shuffled) * val_ratio_trainval)
    val_ids = sorted(shuffled[:val_count])
    train_ids = sorted(shuffled[val_count:])
    return train_ids, val_ids


def _normalize_val_ratio(test_ratio: float, val_ratio: float) -> float:
    trainval_ratio = 1.0 - test_ratio
    if trainval_ratio <= 0:
        return 0.0
    return val_ratio / trainval_ratio


def _build_split_summary(
    *,
    train_ids: list[str],
    val_ids: list[str],
    test_ids: list[str],
    record_lookup: dict[str, SampleRecord],
) -> dict[str, object]:
    all_ids = list(train_ids) + list(val_ids) + list(test_ids)
    records = [record_lookup[sample_id] for sample_id in all_ids]
    total_count = len(records)
    positive_count = sum(1 for record in records if not record.is_negative)
    negative_count = total_count - positive_count
    class_mask_distribution = _build_distribution(records, "class_mask")
    instance_bucket_distribution = _build_distribution(records, "instance_count_bucket")
    positive_ratio = (positive_count / total_count) if total_count else 0.0
    negative_ratio = (negative_count / total_count) if total_count else 0.0
    return {
        "train_count": len(train_ids),
        "val_count": len(val_ids),
        "test_count": len(test_ids),
        "positive_ratio": positive_ratio,
        "negative_ratio": negative_ratio,
        "class_mask_distribution": class_mask_distribution,
        "instance_count_bucket_distribution": instance_bucket_distribution,
    }


def _build_distribution(records: Iterable[SampleRecord], attr: str) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for record in records:
        key = getattr(record, attr)
        distribution[key] = distribution.get(key, 0) + 1
    return distribution
