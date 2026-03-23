from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


_SPLITS: tuple[str, ...] = ("train", "val", "test")


def materialize_dota_view(
    *,
    dota_root: Path,
    split_ids: dict[str, list[str]],
    out_dir: Path,
    link_mode: str = "symlink",
) -> Path:
    src_image_dir = dota_root / "train" / "images"
    src_label_dir = dota_root / "train" / "labelTxt"
    _ensure_dota_dirs(src_image_dir, src_label_dir)
    _prepare_out_dir(out_dir)
    _ensure_dota_layout(out_dir)

    for split in _SPLITS:
        for stem in split_ids.get(split, []):
            image_src = _resolve_image_by_stem(src_image_dir, stem)
            label_src = _resolve_label_by_stem(src_label_dir, stem)
            image_dst = out_dir / split / "images" / image_src.name
            label_dst = out_dir / split / "labelTxt" / label_src.name
            _materialize_path(src=image_src, dst=image_dst, link_mode=link_mode)
            _materialize_path(src=label_src, dst=label_dst, link_mode=link_mode)

    return out_dir


def materialize_yolo_view(
    *,
    dota_root: Path,
    yolo_root: Path,
    split_ids: dict[str, list[str]],
    class_names: tuple[str, ...],
    out_dir: Path,
    link_mode: str = "symlink",
) -> Path:
    src_dota_image_dir = dota_root / "train" / "images"
    src_dota_label_dir = dota_root / "train" / "labelTxt"
    _ensure_dota_dirs(src_dota_image_dir, src_dota_label_dir)
    yolo_images_index = _index_stems(yolo_root / "images")
    yolo_labels_index = _index_stems(yolo_root / "labels", required_suffix=".txt")
    _validate_stem_alignment(
        split_ids=split_ids,
        dota_image_dir=src_dota_image_dir,
        dota_label_dir=src_dota_label_dir,
        yolo_images_index=yolo_images_index,
        yolo_labels_index=yolo_labels_index,
    )

    _prepare_out_dir(out_dir)
    _ensure_yolo_layout(out_dir)
    for split in _SPLITS:
        for stem in split_ids.get(split, []):
            image_src = yolo_images_index[stem]
            label_src = yolo_labels_index[stem]
            image_dst = out_dir / "images" / split / image_src.name
            label_dst = out_dir / "labels" / split / label_src.name
            _materialize_path(src=image_src, dst=image_dst, link_mode=link_mode)
            _materialize_path(src=label_src, dst=label_dst, link_mode=link_mode)

    _write_dataset_yaml(out_dir=out_dir, class_names=class_names)
    return out_dir


def _ensure_dota_dirs(image_dir: Path, label_dir: Path) -> None:
    if not image_dir.exists():
        raise FileNotFoundError(f"DOTA images 目录不存在: {image_dir}")
    if not label_dir.exists():
        raise FileNotFoundError(f"DOTA labelTxt 目录不存在: {label_dir}")


def _prepare_out_dir(out_dir: Path) -> None:
    if out_dir.is_symlink() or out_dir.is_file():
        raise ValueError(f"out_dir 必须是目录路径: {out_dir}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def _ensure_dota_layout(out_dir: Path) -> None:
    for split in _SPLITS:
        (out_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / split / "labelTxt").mkdir(parents=True, exist_ok=True)


def _ensure_yolo_layout(out_dir: Path) -> None:
    for split in _SPLITS:
        (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)


def _resolve_image_by_stem(image_dir: Path, stem: str) -> Path:
    matches = sorted(image_dir.glob(f"{stem}.*"))
    if not matches:
        raise FileNotFoundError(f"找不到样本 {stem} 的图片文件: {image_dir}")
    if len(matches) > 1:
        raise ValueError(f"multiple images matched for stem {stem}: {matches}")
    return matches[0]


def _resolve_label_by_stem(label_dir: Path, stem: str) -> Path:
    label_path = label_dir / f"{stem}.txt"
    if not label_path.exists():
        raise FileNotFoundError(f"找不到样本 {stem} 的标注文件: {label_dir}")
    return label_path


def _materialize_path(*, src: Path, dst: Path, link_mode: str) -> None:
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            raise IsADirectoryError(f"目标路径是目录，无法物化文件: {dst}")
        dst.unlink()
    if link_mode == "copy":
        shutil.copy2(src, dst)
        return
    if link_mode != "symlink":
        raise ValueError(f"不支持的 link_mode: {link_mode}")
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)


def _index_stems(root: Path, *, required_suffix: str | None = None) -> dict[str, Path]:
    if not root.exists():
        return {}
    indexed: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if required_suffix is not None and path.suffix != required_suffix:
            continue
        if path.stem in indexed:
            raise ValueError(
                f"duplicate stem: {path.stem} ({indexed[path.stem]} vs {path})"
            )
        indexed[path.stem] = path
    return indexed


def _validate_stem_alignment(
    *,
    split_ids: dict[str, list[str]],
    dota_image_dir: Path,
    dota_label_dir: Path,
    yolo_images_index: dict[str, Path],
    yolo_labels_index: dict[str, Path],
) -> None:
    for split in _SPLITS:
        for stem in split_ids.get(split, []):
            _resolve_image_by_stem(dota_image_dir, stem)
            _resolve_label_by_stem(dota_label_dir, stem)
            if stem not in yolo_images_index or stem not in yolo_labels_index:
                raise ValueError(f"stem mismatch: {stem}")


def _write_dataset_yaml(*, out_dir: Path, class_names: tuple[str, ...]) -> None:
    path_value = json.dumps(str(out_dir), ensure_ascii=False)
    train_value = json.dumps("images/train", ensure_ascii=False)
    val_value = json.dumps("images/val", ensure_ascii=False)
    test_value = json.dumps("images/test", ensure_ascii=False)
    names_value = json.dumps(list(class_names), ensure_ascii=False)
    content = (
        f"path: {path_value}\n"
        f"train: {train_value}\n"
        f"val: {val_value}\n"
        f"test: {test_value}\n"
        f"nc: {len(class_names)}\n"
        f"names: {names_value}\n"
    )
    (out_dir / "dataset.yaml").write_text(content, encoding="utf-8")
