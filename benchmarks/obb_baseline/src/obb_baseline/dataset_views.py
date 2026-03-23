from __future__ import annotations

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
    return matches[0]


def _resolve_label_by_stem(label_dir: Path, stem: str) -> Path:
    label_path = label_dir / f"{stem}.txt"
    if not label_path.exists():
        raise FileNotFoundError(f"找不到样本 {stem} 的标注文件: {label_dir}")
    return label_path


def _materialize_path(*, src: Path, dst: Path, link_mode: str) -> None:
    if dst.exists() or dst.is_symlink():
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
    names_block = "\n".join(f"  - {name}" for name in class_names)
    content = (
        f"path: {out_dir}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        f"nc: {len(class_names)}\n"
        "names:\n"
        f"{names_block}\n"
    )
    (out_dir / "dataset.yaml").write_text(content, encoding="utf-8")
