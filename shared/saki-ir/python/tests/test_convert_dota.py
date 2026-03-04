from __future__ import annotations

from pathlib import Path

import pytest

from saki_ir.convert import ConversionContext, struct_to_dict
from saki_ir.convert.dota_obb import dota_txt_to_ir, ir_to_dota_txt
from saki_ir.convert.io import load_dota_dataset, save_dota_dataset
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _items_by_kind(batch: ir.DataBatchIR, kind: str):
    return [item for item in batch.items if item.WhichOneof("item") == kind]


def _write_min_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )


def test_dota_import_10_column_and_headers() -> None:
    txt = "\n".join(
        [
            "imagesource:GoogleEarth",
            "gsd:0.5",
            "10 10 40 10 40 30 10 30 ship 1",
            "",
        ]
    )
    batch = dota_txt_to_ir(
        txt,
        image_w=100,
        image_h=80,
        class_names=["ship"],
        image_relpath="train/images/img1.png",
        ctx=ConversionContext(strict=True),
    )

    samples = _items_by_kind(batch, "sample")
    anns = _items_by_kind(batch, "annotation")
    assert len(samples) == 1
    assert len(anns) == 1

    sample = samples[0].sample
    ann = anns[0].annotation
    meta = struct_to_dict(sample.meta)
    attrs = struct_to_dict(ann.attrs)

    assert meta["dota"]["imagesource"] == "GoogleEarth"
    assert float(meta["dota"]["gsd"]) == pytest.approx(0.5, abs=1e-6)
    assert attrs["dota"]["difficulty"] == 1

    obb = ann.geometry.obb
    assert obb.cx == pytest.approx(25.0, abs=1e-6)
    assert obb.cy == pytest.approx(20.0, abs=1e-6)
    assert obb.width > 0
    assert obb.height > 0


def test_dota_import_9_column_defaults_difficulty_zero() -> None:
    txt = "0 0 20 0 20 10 0 10 plane\n"
    batch = dota_txt_to_ir(
        txt,
        image_w=20,
        image_h=10,
        class_names=None,
        image_relpath="train/images/a.png",
        ctx=ConversionContext(strict=True),
    )

    ann = _items_by_kind(batch, "annotation")[0].annotation
    attrs = struct_to_dict(ann.attrs)
    assert attrs["dota"]["difficulty"] == 0


def test_dota_export_roundtrip_writes_headers_and_difficulty() -> None:
    txt = "\n".join(
        [
            "imagesource:GoogleEarth",
            "gsd:0.125",
            "10 10 40 10 40 30 10 30 ship 1",
            "",
        ]
    )
    batch = dota_txt_to_ir(
        txt,
        image_w=100,
        image_h=80,
        class_names=["ship"],
        image_relpath="train/images/img1.png",
        ctx=ConversionContext(strict=True),
    )
    out = ir_to_dota_txt(batch, ctx=ConversionContext(strict=True, yolo_float_precision=6))
    lines = [line.strip() for line in out.splitlines() if line.strip()]

    assert lines[0] == "imagesource:GoogleEarth"
    assert lines[1].startswith("gsd:")
    last = lines[-1].split()
    assert len(last) == 10
    assert last[8] == "ship"
    assert last[9] == "1"


def test_dota_poly8_best_effort_fit_to_obb() -> None:
    txt = "10 10 40 12 38 30 12 28 vehicle 0\n"
    batch = dota_txt_to_ir(
        txt,
        image_w=100,
        image_h=100,
        class_names=None,
        image_relpath="train/images/img1.png",
        ctx=ConversionContext(strict=True),
    )

    ann = _items_by_kind(batch, "annotation")[0].annotation
    obb = ann.geometry.obb
    assert obb.width > 0
    assert obb.height > 0

    exported = ir_to_dota_txt(batch, ctx=ConversionContext(strict=True, yolo_float_precision=4))
    rows = [line for line in exported.splitlines() if line and ":" not in line]
    assert len(rows) == 1
    assert len(rows[0].split()) == 10


def test_dota_dataset_io_mmrotate_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "dota_mmrotate"
    _write_min_png(root / "train" / "images" / "img1.png")
    (root / "train" / "labelTxt").mkdir(parents=True, exist_ok=True)
    (root / "train" / "labelTxt" / "img1.txt").write_text(
        "\n".join(
            [
                "imagesource:GoogleEarth",
                "gsd:0.25",
                "10 10 40 10 40 30 10 30 ship 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    batch = load_dota_dataset(
        root,
        "train",
        ctx=ConversionContext(strict=True, read_images=False),
    )
    assert len(_items_by_kind(batch, "sample")) == 1
    assert len(_items_by_kind(batch, "annotation")) == 1

    out_root = tmp_path / "dota_out"
    save_dota_dataset(
        batch,
        out_root,
        "train",
        ctx=ConversionContext(strict=True, naming="uuid"),
    )
    out_txt_files = list((out_root / "train" / "labelTxt").rglob("*.txt"))
    assert len(out_txt_files) == 1
    content = out_txt_files[0].read_text(encoding="utf-8")
    assert "ship 1" in content


def test_dota_load_supports_images_split_layout(tmp_path: Path) -> None:
    root = tmp_path / "dota_split"
    _write_min_png(root / "images" / "train" / "img1.png")
    (root / "labelTxt" / "train").mkdir(parents=True, exist_ok=True)
    (root / "labelTxt" / "train" / "img1.txt").write_text(
        "10 10 40 10 40 30 10 30 ship 1\n",
        encoding="utf-8",
    )

    batch = load_dota_dataset(
        root,
        "train",
        ctx=ConversionContext(strict=True, read_images=False),
    )
    assert len(_items_by_kind(batch, "sample")) == 1
    assert len(_items_by_kind(batch, "annotation")) == 1
