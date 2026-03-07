from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from saki_ir.convert import ConversionContext, ConversionError, struct_to_dict, voc_xml_to_ir, ir_to_voc_xml
from saki_ir.convert.base import ERR_CONVERT_SCHEMA
from saki_ir.convert.io import load_voc_dataset, save_voc_dataset
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _items_by_kind(batch: ir.DataBatchIR, kind: str):
    return [item for item in batch.items if item.WhichOneof("item") == kind]


def test_voc_tlbr_to_ir_tlwh() -> None:
    xml_text = _fixture_path("voc_min.xml").read_text(encoding="utf-8")
    batch = voc_xml_to_ir(xml_text, image_relpath="JPEGImages/img1.jpg", ctx=ConversionContext(strict=True))

    samples = _items_by_kind(batch, "sample")
    anns = _items_by_kind(batch, "annotation")
    assert len(samples) == 1
    assert len(anns) == 1

    sample = samples[0].sample
    rect = anns[0].annotation.geometry.rect
    assert sample.width == 640
    assert sample.height == 480
    assert rect.x == pytest.approx(10.0, abs=1e-6)
    assert rect.y == pytest.approx(20.0, abs=1e-6)
    assert rect.width == pytest.approx(100.0, abs=1e-6)
    assert rect.height == pytest.approx(40.0, abs=1e-6)


def test_voc_ir_to_xml_roundtrip() -> None:
    xml_text = _fixture_path("voc_min.xml").read_text(encoding="utf-8")
    ctx = ConversionContext(strict=True, voc_coord_base=0)
    batch = voc_xml_to_ir(xml_text, image_relpath="JPEGImages/img1.jpg", ctx=ctx)
    out_xml = ir_to_voc_xml(batch, ctx=ctx)

    root = ET.fromstring(out_xml)
    assert root.findtext("filename") == "img1.jpg"
    assert root.findtext("object/name") == "car"
    assert root.findtext("object/bndbox/xmin") == "10"
    assert root.findtext("object/bndbox/ymin") == "20"
    assert root.findtext("object/bndbox/xmax") == "110"
    assert root.findtext("object/bndbox/ymax") == "60"


def test_voc_coord_base_one_import_export() -> None:
    xml_text = """
<annotation>
  <filename>img1.jpg</filename>
  <size><width>640</width><height>480</height><depth>3</depth></size>
  <object>
    <name>car</name>
    <bndbox><xmin>11</xmin><ymin>21</ymin><xmax>111</xmax><ymax>61</ymax></bndbox>
  </object>
</annotation>
""".strip()

    ctx = ConversionContext(strict=True, voc_coord_base=1)
    batch = voc_xml_to_ir(xml_text, image_relpath="JPEGImages/img1.jpg", ctx=ctx)
    rect = _items_by_kind(batch, "annotation")[0].annotation.geometry.rect
    assert rect.x == pytest.approx(10.0, abs=1e-6)
    assert rect.y == pytest.approx(20.0, abs=1e-6)

    out_xml = ir_to_voc_xml(batch, ctx=ctx)
    root = ET.fromstring(out_xml)
    assert root.findtext("object/bndbox/xmin") == "11"
    assert root.findtext("object/bndbox/ymin") == "21"
    assert root.findtext("object/bndbox/xmax") == "111"
    assert root.findtext("object/bndbox/ymax") == "61"


def test_voc_export_requires_single_sample() -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(sample=ir.SampleRecord(id="s1", width=10, height=10)),
            ir.DataItemIR(sample=ir.SampleRecord(id="s2", width=10, height=10)),
        ]
    )

    with pytest.raises(ConversionError) as exc:
        ir_to_voc_xml(batch, ctx=ConversionContext(strict=True))
    assert exc.value.code == ERR_CONVERT_SCHEMA


def test_voc_external_refs_written_when_enabled() -> None:
    xml_text = _fixture_path("voc_min.xml").read_text(encoding="utf-8")
    batch = voc_xml_to_ir(xml_text, image_relpath="JPEGImages/img1.jpg", ctx=ConversionContext(include_external_ref=True))

    sample = _items_by_kind(batch, "sample")[0].sample
    ann = _items_by_kind(batch, "annotation")[0].annotation
    sample_meta = struct_to_dict(sample.meta)
    ann_attrs = struct_to_dict(ann.attrs)
    assert sample_meta["external"]["source"] == "voc"
    assert sample_meta["external"]["relpath"] == "JPEGImages/img1.jpg"
    assert ann_attrs["external"]["category_key"] == "car"


def test_voc_dataset_io_load_and_save(tmp_path: Path) -> None:
    root = tmp_path / "voc"
    (root / "Annotations").mkdir(parents=True)
    (root / "JPEGImages").mkdir(parents=True)
    (root / "ImageSets" / "Main").mkdir(parents=True)

    (root / "Annotations" / "img1.xml").write_text(_fixture_path("voc_min.xml").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "ImageSets" / "Main" / "train.txt").write_text("img1\n", encoding="utf-8")

    ctx = ConversionContext(strict=True)
    batch = load_voc_dataset(root, "train", ctx)
    out_root = tmp_path / "voc_out"
    save_voc_dataset(batch, out_root, "train", ctx)

    assert (out_root / "Annotations" / "img1.xml").exists()
    split_text = (out_root / "ImageSets" / "Main" / "train.txt").read_text(encoding="utf-8")
    assert split_text.strip() == "img1"
