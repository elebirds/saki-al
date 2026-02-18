from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from saki_ir.convert import ConversionContext, ConversionError, ConversionReport, ir_to_yolo_txt, struct_to_dict, yolo_txt_to_ir
from saki_ir.convert.base import ERR_CONVERT_SCHEMA
from saki_ir.convert.io import load_yolo_dataset, save_yolo_dataset
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _items_by_kind(batch: ir.DataBatchIR, kind: str):
    return [item for item in batch.items if item.WhichOneof("item") == kind]


def _one_sample_batch() -> ir.DataBatchIR:
    return ir.DataBatchIR(
        items=[
            ir.DataItemIR(label=ir.LabelRecord(id="l1", name="car")),
            ir.DataItemIR(sample=ir.SampleRecord(id="s1", width=640, height=480)),
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="a1",
                    sample_id="s1",
                    label_id="l1",
                    confidence=1.0,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=10.0, y=20.0, width=100.0, height=40.0)),
                )
            ),
        ]
    )


def test_yolo_normalized_center_roundtrip() -> None:
    txt = _fixture_path("yolo_min.txt").read_text(encoding="utf-8")
    ctx = ConversionContext(strict=True, yolo_is_normalized=True, yolo_float_precision=6)

    batch = yolo_txt_to_ir(
        txt,
        image_w=640,
        image_h=480,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ctx,
    )
    ann = _items_by_kind(batch, "annotation")[0].annotation
    rect = ann.geometry.rect
    assert rect.x == pytest.approx(10.0, abs=1e-3)
    assert rect.y == pytest.approx(20.0, abs=1e-3)
    assert rect.width == pytest.approx(100.0, abs=1e-3)
    assert rect.height == pytest.approx(40.0, abs=1e-3)

    out = ir_to_yolo_txt(batch, image_w=640, image_h=480, class_to_index={"car": 0}, ctx=ctx)
    parts = out.strip().split()
    assert parts[0] == "0"
    assert float(parts[1]) == pytest.approx(0.09375, abs=1e-6)
    assert float(parts[2]) == pytest.approx(0.083333, abs=1e-6)
    assert float(parts[3]) == pytest.approx(0.15625, abs=1e-6)
    assert float(parts[4]) == pytest.approx(0.083333, abs=1e-6)


def test_yolo_missing_size_strict_raise() -> None:
    with pytest.raises(ConversionError) as exc:
        yolo_txt_to_ir(
            "0 0.5 0.5 0.2 0.2\n",
            image_w=None,
            image_h=None,
            class_names=["car"],
            image_relpath="a.jpg",
            ctx=ConversionContext(strict=True, yolo_is_normalized=True),
        )
    assert exc.value.code == ERR_CONVERT_SCHEMA


def test_yolo_missing_size_lenient_report() -> None:
    report = ConversionReport()
    batch = yolo_txt_to_ir(
        "0 0.5 0.5 0.2 0.2\n",
        image_w=None,
        image_h=None,
        class_names=["car"],
        image_relpath="a.jpg",
        ctx=ConversionContext(strict=False, yolo_is_normalized=True),
        report=report,
    )

    assert len(_items_by_kind(batch, "sample")) == 1
    assert len(_items_by_kind(batch, "annotation")) == 0
    assert len(report.errors) == 1


def test_yolo_export_clip_vs_no_clip() -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(label=ir.LabelRecord(id="l1", name="car")),
            ir.DataItemIR(sample=ir.SampleRecord(id="s1", width=100, height=100)),
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="a1",
                    sample_id="s1",
                    label_id="l1",
                    confidence=1.0,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=90.0, y=95.0, width=20.0, height=20.0)),
                )
            ),
        ]
    )

    clipped = ir_to_yolo_txt(
        batch,
        image_w=100,
        image_h=100,
        class_to_index={"car": 0},
        ctx=ConversionContext(clip_on_export=True, yolo_is_normalized=False),
    )
    unclipped = ir_to_yolo_txt(
        batch,
        image_w=100,
        image_h=100,
        class_to_index={"car": 0},
        ctx=ConversionContext(clip_on_export=False, yolo_is_normalized=False),
    )

    clipped_vals = [float(v) for v in clipped.split()[1:]]
    unclipped_vals = [float(v) for v in unclipped.split()[1:]]
    assert clipped_vals == pytest.approx([95.0, 97.5, 10.0, 5.0], abs=1e-6)
    assert unclipped_vals == pytest.approx([100.0, 105.0, 20.0, 20.0], abs=1e-6)


def test_yolo_external_refs_written_when_enabled() -> None:
    txt = _fixture_path("yolo_min.txt").read_text(encoding="utf-8")
    batch = yolo_txt_to_ir(
        txt,
        image_w=640,
        image_h=480,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ConversionContext(include_external_ref=True),
    )

    sample = _items_by_kind(batch, "sample")[0].sample
    ann = _items_by_kind(batch, "annotation")[0].annotation
    sample_meta = struct_to_dict(sample.meta)
    ann_attrs = struct_to_dict(ann.attrs)

    assert sample_meta["external"]["source"] == "yolo"
    assert sample_meta["external"]["relpath"] == "images/train/img1.jpg"
    assert ann_attrs["external"]["category_key"] == "0"


def test_yolo_dataset_io_save_and_load(tmp_path: Path) -> None:
    batch = _one_sample_batch()
    root = tmp_path / "yolo"
    (root / "images" / "train").mkdir(parents=True)

    # 使用最小合法 PNG 头，避免未来 read_images=True 时测试因非法图片失败。
    (root / "images" / "train" / "s1.jpg").write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )

    save_ctx = ConversionContext(strict=True, naming="uuid", yolo_is_normalized=False)
    save_yolo_dataset(batch, root, "train", ctx=save_ctx)

    load_ctx = ConversionContext(strict=True, yolo_is_normalized=False, read_images=False)
    loaded = load_yolo_dataset(root, "train", ctx=load_ctx)

    samples = _items_by_kind(loaded, "sample")
    anns = _items_by_kind(loaded, "annotation")
    assert len(samples) == 1
    assert len(anns) == 1
    rect = anns[0].annotation.geometry.rect
    assert rect.x == pytest.approx(10.0, abs=1e-6)
    assert rect.y == pytest.approx(20.0, abs=1e-6)
    assert rect.width == pytest.approx(100.0, abs=1e-6)
    assert rect.height == pytest.approx(40.0, abs=1e-6)


def test_yolo_save_skip_when_normalized_without_image_size(tmp_path: Path) -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(label=ir.LabelRecord(id="l1", name="car")),
            ir.DataItemIR(sample=ir.SampleRecord(id="s0", width=0, height=0)),
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="a1",
                    sample_id="s0",
                    label_id="l1",
                    confidence=1.0,
                    geometry=ir.Geometry(rect=ir.RectGeometry(x=1.0, y=1.0, width=2.0, height=2.0)),
                )
            ),
        ]
    )
    report = ConversionReport()
    save_yolo_dataset(batch, tmp_path / "yolo", "train", ctx=ConversionContext(strict=False), report=report)
    assert report.errors
    assert not list((tmp_path / "yolo" / "labels" / "train").rglob("*.txt"))


def test_yolo_save_writes_empty_file_for_negative_sample(tmp_path: Path) -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(sample=ir.SampleRecord(id="s-empty", width=640, height=480)),
        ]
    )
    root = tmp_path / "yolo_empty"
    save_yolo_dataset(batch, root, "train", ctx=ConversionContext(strict=True, naming="uuid"))
    txt = root / "labels" / "train" / "s-empty.txt"
    assert txt.exists()
    assert txt.read_text(encoding="utf-8") == ""


def test_yolo_load_yaml_fallback_without_pyyaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "yolo_fallback"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "images" / "train" / "img1.jpg").write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )
    (root / "labels" / "train" / "img1.txt").write_text("0 10 10 4 4\n", encoding="utf-8")
    (root / "data.yaml").write_text("train: images/train\nnames:\n  0: car\n", encoding="utf-8")

    original_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "yaml":
            raise ImportError("blocked for test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    report = ConversionReport()
    batch = load_yolo_dataset(
        root,
        "train",
        ctx=ConversionContext(strict=False, read_images=False, yolo_is_normalized=False),
        report=report,
    )

    assert report.warnings
    assert "pyyaml" in report.warnings[0]
    assert len(_items_by_kind(batch, "annotation")) == 1
