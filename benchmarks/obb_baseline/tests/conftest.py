"""Fixtures for obb_baseline tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tiny_dota_export(tmp_path: Path) -> Path:
    root = tmp_path / "tiny_dota_export"
    image_dir = root / "train" / "images"
    ann_dir = root / "train" / "labelTxt"
    image_dir.mkdir(parents=True)
    ann_dir.mkdir(parents=True)

    samples: dict[str, list[str]] = {
        "sample_001": [],
        "sample_002": ["0 0 10 0 10 10 0 10 pattern_a 0"],
        "sample_003": [
            "0 0 10 0 10 10 0 10 pattern_b 0",
            "10 10 20 10 20 20 10 20 pattern_c 0",
        ],
        "sample_004": [
            "0 0 10 0 10 10 0 10 pattern_a 0",
            "10 0 20 0 20 10 10 10 pattern_a 0",
            "0 10 10 10 10 20 0 20 pattern_a 0",
            "20 20 30 20 30 30 20 30 pattern_a 0",
        ],
        "sample_005": [
            "0 0 10 0 10 10 0 10 pattern_c 0",
            "10 0 20 0 20 10 10 10 pattern_c 0",
            "0 10 10 10 10 20 0 20 pattern_c 0",
            "20 20 30 20 30 30 20 30 pattern_c 0",
            "30 30 40 30 40 40 30 40 pattern_c 0",
        ],
        "sample_006": [
            "0 0 10 0 10 10 0 10 pattern_a 0",
            "10 10 20 10 20 20 10 20 pattern_b 0",
            "20 20 30 20 30 30 20 30 pattern_b 0",
        ],
        "sample_007": ["0 0 10 0 10 10 0 10 pattern_b 0"],
        "sample_008": [
            "0 0 10 0 10 10 0 10 pattern_c 0",
            "10 10 20 10 20 20 10 20 pattern_c 0",
        ],
        "sample_009": [
            "0 0 10 0 10 10 0 10 pattern_a 0",
            "10 10 20 10 20 20 10 20 pattern_b 0",
            "20 20 30 20 30 30 20 30 pattern_c 0",
        ],
        "sample_010": ["0 0 10 0 10 10 0 10 pattern_c 0"],
        "sample_011": [
            "0 0 10 0 10 10 0 10 pattern_a 0",
            "10 10 20 10 20 20 10 20 pattern_b 0",
        ],
        "sample_012": [
            "0 0 10 0 10 10 0 10 pattern_b 0",
            "10 0 20 0 20 10 10 10 pattern_b 0",
            "0 10 10 10 10 20 0 20 pattern_b 0",
            "20 20 30 20 30 30 20 30 pattern_b 0",
        ],
    }

    for stem, lines in samples.items():
        (image_dir / f"{stem}.png").write_bytes(b"")
        ann_path = ann_dir / f"{stem}.txt"
        payload = ["imagesource:GoogleEarth", "gsd:0.3", *lines]
        ann_path.write_text("\n".join(payload) + "\n", encoding="utf-8")

    return root


@pytest.fixture()
def sample_inventory(tiny_dota_export: Path):
    from obb_baseline.splitters import scan_dota_export

    return scan_dota_export(
        tiny_dota_export,
        class_names=("pattern_a", "pattern_b", "pattern_c"),
    )


@pytest.fixture()
def sample_inventory_with_small_bucket(sample_inventory):
    return sample_inventory


@pytest.fixture()
def tiny_yolo_export(tmp_path: Path) -> Path:
    root = tmp_path / "tiny_yolo_export"
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    samples_by_split: dict[str, tuple[str, ...]] = {
        "train": ("sample_001", "sample_002", "sample_003"),
        "val": ("sample_004",),
        "test": ("sample_005",),
    }
    for split, stems in samples_by_split.items():
        for stem in stems:
            (root / "images" / split / f"{stem}.png").write_bytes(b"")
            (root / "labels" / split / f"{stem}.txt").write_text("", encoding="utf-8")

    return root


@pytest.fixture()
def tiny_yolo_export_with_mismatch(tmp_path: Path) -> Path:
    root = tmp_path / "tiny_yolo_export_with_mismatch"
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    samples_by_split: dict[str, tuple[str, ...]] = {
        "train": ("sample_001", "sample_002", "mismatch_003"),
        "val": ("sample_004",),
        "test": ("sample_005",),
    }
    for split, stems in samples_by_split.items():
        for stem in stems:
            (root / "images" / split / f"{stem}.png").write_bytes(b"")
            (root / "labels" / split / f"{stem}.txt").write_text("", encoding="utf-8")

    return root
