from __future__ import annotations

import json
from pathlib import Path

import pytest

from saki_ir.convert import ConversionContext, ConversionError, ConversionReport, coco_to_ir, ir_to_coco, struct_to_dict
from saki_ir.convert.base import ERR_CONVERT_GEOMETRY
from saki_ir.convert.io import load_coco_dataset, save_coco_dataset
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _items_by_kind(batch: ir.DataBatchIR, kind: str):
    return [item for item in batch.items if item.WhichOneof("item") == kind]


def test_coco_bbox_roundtrip_semantics() -> None:
    coco = json.loads(_fixture_path("coco_min.json").read_text(encoding="utf-8"))
    ctx = ConversionContext(strict=True)

    batch = coco_to_ir(coco, image_root=None, ctx=ctx)
    anns = _items_by_kind(batch, "annotation")
    assert len(anns) == 1
    rect = anns[0].annotation.geometry.rect
    assert rect.x == pytest.approx(10.0, abs=1e-6)
    assert rect.y == pytest.approx(20.0, abs=1e-6)
    assert rect.width == pytest.approx(100.0, abs=1e-6)
    assert rect.height == pytest.approx(40.0, abs=1e-6)

    out = ir_to_coco(batch, ctx=ctx)
    assert len(out["images"]) == 1
    assert len(out["categories"]) == 1
    assert len(out["annotations"]) == 1
    assert out["annotations"][0]["bbox"] == pytest.approx([10.0, 20.0, 100.0, 40.0], abs=1e-6)


def test_coco_export_clip_vs_no_clip() -> None:
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

    clipped = ir_to_coco(batch, ctx=ConversionContext(clip_on_export=True))
    unclipped = ir_to_coco(batch, ctx=ConversionContext(clip_on_export=False))

    assert clipped["annotations"][0]["bbox"] == pytest.approx([90.0, 95.0, 10.0, 5.0], abs=1e-6)
    assert unclipped["annotations"][0]["bbox"] == pytest.approx([90.0, 95.0, 20.0, 20.0], abs=1e-6)


def test_coco_external_refs_written_when_enabled() -> None:
    coco = json.loads(_fixture_path("coco_min.json").read_text(encoding="utf-8"))
    batch = coco_to_ir(coco, image_root=None, ctx=ConversionContext(include_external_ref=True))

    sample = _items_by_kind(batch, "sample")[0].sample
    ann = _items_by_kind(batch, "annotation")[0].annotation
    sample_meta = struct_to_dict(sample.meta)
    ann_attrs = struct_to_dict(ann.attrs)

    assert sample_meta["external"]["source"] == "coco"
    assert sample_meta["external"]["sample_key"] == "1"
    assert ann_attrs["external"]["ann_key"] == "10"
    assert ann_attrs["external"]["category_key"] == "3"


def test_coco_lenient_skips_invalid_annotation() -> None:
    coco = {
        "images": [{"id": 1, "file_name": "a.jpg", "width": 64, "height": 64}],
        "categories": [{"id": 1, "name": "car"}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 2, -3, 4]}],
    }

    with pytest.raises(ConversionError) as exc:
        coco_to_ir(coco, image_root=None, ctx=ConversionContext(strict=True))
    assert exc.value.code == ERR_CONVERT_GEOMETRY

    report = ConversionReport()
    batch = coco_to_ir(coco, image_root=None, ctx=ConversionContext(strict=False), report=report)
    assert len(_items_by_kind(batch, "annotation")) == 0
    assert len(report.errors) == 1


def test_coco_dataset_io_load_and_save(tmp_path: Path) -> None:
    src = _fixture_path("coco_min.json")
    in_json = tmp_path / "instances.json"
    out_json = tmp_path / "out" / "instances_out.json"
    in_json.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    ctx = ConversionContext(strict=True)
    batch = load_coco_dataset(in_json, image_root=tmp_path / "images", ctx=ctx)
    save_coco_dataset(batch, out_json, image_root=tmp_path / "images", ctx=ctx)

    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert set(saved.keys()) == {"images", "categories", "annotations"}
    assert len(saved["images"]) == 1
    assert len(saved["categories"]) == 1
    assert len(saved["annotations"]) == 1


def test_coco_export_naming_strategy_uuid() -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(sample=ir.SampleRecord(id="sample-uuid", width=100, height=100)),
        ]
    )
    out = ir_to_coco(batch, ctx=ConversionContext(strict=True, naming="uuid"))
    assert out["images"][0]["file_name"] == "sample-uuid.jpg"
