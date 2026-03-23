from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from obb_baseline.dataset_views import materialize_dota_view, materialize_yolo_view


def test_materialize_dota_view_materializes_only_selected_ids(
    tmp_path: Path,
    tiny_dota_export: Path,
) -> None:
    split_ids = {
        "train": ["sample_001", "sample_003"],
        "val": ["sample_002"],
        "test": [],
    }
    out_dir = tmp_path / "dota_view"

    view_root = materialize_dota_view(
        dota_root=tiny_dota_export,
        split_ids=split_ids,
        out_dir=out_dir,
    )

    assert view_root == out_dir
    train_images = sorted(path.stem for path in (out_dir / "train" / "images").glob("*"))
    train_labels = sorted(path.stem for path in (out_dir / "train" / "labelTxt").glob("*.txt"))
    val_images = sorted(path.stem for path in (out_dir / "val" / "images").glob("*"))
    val_labels = sorted(path.stem for path in (out_dir / "val" / "labelTxt").glob("*.txt"))
    test_images = sorted(path.stem for path in (out_dir / "test" / "images").glob("*"))
    test_labels = sorted(path.stem for path in (out_dir / "test" / "labelTxt").glob("*.txt"))

    assert train_images == ["sample_001", "sample_003"]
    assert train_labels == ["sample_001", "sample_003"]
    assert val_images == ["sample_002"]
    assert val_labels == ["sample_002"]
    assert test_images == []
    assert test_labels == []
    assert "sample_004" not in train_images + val_images + test_images


def test_materialize_dota_view_rerun_does_not_keep_stale_files(
    tmp_path: Path,
    tiny_dota_export: Path,
) -> None:
    out_dir = tmp_path / "dota_view_rerun"
    materialize_dota_view(
        dota_root=tiny_dota_export,
        split_ids={"train": ["sample_001"], "val": [], "test": []},
        out_dir=out_dir,
    )

    materialize_dota_view(
        dota_root=tiny_dota_export,
        split_ids={"train": ["sample_002"], "val": [], "test": []},
        out_dir=out_dir,
    )

    train_images = sorted(path.stem for path in (out_dir / "train" / "images").glob("*"))
    train_labels = sorted(path.stem for path in (out_dir / "train" / "labelTxt").glob("*.txt"))
    assert train_images == ["sample_002"]
    assert train_labels == ["sample_002"]


def test_materialize_dota_view_raises_when_multiple_images_match_same_stem(
    tmp_path: Path,
    tiny_dota_export: Path,
) -> None:
    image_dir = tiny_dota_export / "train" / "images"
    (image_dir / "sample_001.jpg").write_bytes(b"")

    with pytest.raises(ValueError, match="multiple images"):
        materialize_dota_view(
            dota_root=tiny_dota_export,
            split_ids={"train": ["sample_001"], "val": [], "test": []},
            out_dir=tmp_path / "dota_view_multi_image",
        )


def test_materialize_yolo_view_raises_when_stems_mismatch(
    tmp_path: Path,
    tiny_dota_export: Path,
    tiny_yolo_export_with_mismatch: Path,
) -> None:
    split_ids = {
        "train": ["sample_001", "sample_002", "sample_003"],
        "val": [],
        "test": [],
    }

    with pytest.raises(ValueError, match="stem mismatch"):
        materialize_yolo_view(
            dota_root=tiny_dota_export,
            yolo_root=tiny_yolo_export_with_mismatch,
            split_ids=split_ids,
            class_names=("pattern_a", "pattern_b", "pattern_c"),
            out_dir=tmp_path / "yolo_view_mismatch",
        )


def test_materialize_yolo_view_raises_when_duplicate_stem_in_source(
    tmp_path: Path,
    tiny_dota_export: Path,
    tiny_yolo_export_with_duplicate_stem: Path,
) -> None:
    with pytest.raises(ValueError, match="duplicate stem"):
        materialize_yolo_view(
            dota_root=tiny_dota_export,
            yolo_root=tiny_yolo_export_with_duplicate_stem,
            split_ids={"train": ["sample_001"], "val": [], "test": []},
            class_names=("pattern_a", "pattern_b", "pattern_c"),
            out_dir=tmp_path / "yolo_view_duplicate",
        )


def test_materialize_yolo_view_fallbacks_to_copy_and_writes_yaml(
    tmp_path: Path,
    tiny_dota_export: Path,
    tiny_yolo_export: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    split_ids = {
        "train": ["sample_001", "sample_002"],
        "val": ["sample_004"],
        "test": ["sample_005"],
    }
    out_dir = tmp_path / "yolo_view_ok"
    original_symlink = os.symlink

    def _raise_for_view(src, dst, *args, **kwargs):
        dst_path = Path(dst)
        if out_dir in dst_path.parents or dst_path == out_dir:
            raise OSError("simulated symlink failure")
        return original_symlink(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "symlink", _raise_for_view)

    view_root = materialize_yolo_view(
        dota_root=tiny_dota_export,
        yolo_root=tiny_yolo_export,
        split_ids=split_ids,
        class_names=("pattern_a", "pattern_b", "pattern_c"),
        out_dir=out_dir,
        link_mode="symlink",
    )

    assert view_root == out_dir
    assert (out_dir / "images" / "train" / "sample_001.png").is_file()
    assert (out_dir / "labels" / "train" / "sample_001.txt").is_file()
    dataset_yaml = yaml.safe_load((out_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["path"] == str(out_dir)
    assert dataset_yaml["train"] == "images/train"
    assert dataset_yaml["val"] == "images/val"
    assert dataset_yaml["test"] == "images/test"
    assert dataset_yaml["names"] == ["pattern_a", "pattern_b", "pattern_c"]


def test_materialize_yolo_view_rerun_does_not_keep_stale_files(
    tmp_path: Path,
    tiny_dota_export: Path,
    tiny_yolo_export: Path,
) -> None:
    out_dir = tmp_path / "yolo_view_rerun"
    materialize_yolo_view(
        dota_root=tiny_dota_export,
        yolo_root=tiny_yolo_export,
        split_ids={"train": ["sample_001"], "val": [], "test": []},
        class_names=("pattern_a", "pattern_b", "pattern_c"),
        out_dir=out_dir,
    )

    materialize_yolo_view(
        dota_root=tiny_dota_export,
        yolo_root=tiny_yolo_export,
        split_ids={"train": ["sample_002"], "val": [], "test": []},
        class_names=("pattern_a", "pattern_b", "pattern_c"),
        out_dir=out_dir,
    )

    train_images = sorted(path.stem for path in (out_dir / "images" / "train").glob("*"))
    train_labels = sorted(path.stem for path in (out_dir / "labels" / "train").glob("*.txt"))
    assert train_images == ["sample_002"]
    assert train_labels == ["sample_002"]


def test_materialize_yolo_view_writes_yaml_safe_scalars(
    tmp_path: Path,
    tiny_dota_export: Path,
    tiny_yolo_export: Path,
) -> None:
    out_dir = tmp_path / "yolo_view_yaml_safe"
    class_names = ("normal", "yes", "a:b", "x # y", "[brackets]")

    materialize_yolo_view(
        dota_root=tiny_dota_export,
        yolo_root=tiny_yolo_export,
        split_ids={"train": ["sample_001"], "val": [], "test": []},
        class_names=class_names,
        out_dir=out_dir,
    )

    dataset_yaml = yaml.safe_load((out_dir / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_yaml["names"] == list(class_names)
