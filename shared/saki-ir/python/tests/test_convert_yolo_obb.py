from __future__ import annotations

from pathlib import Path

import pytest

from saki_ir.convert import ConversionContext, ConversionError, ConversionReport
from saki_ir.convert.base import ERR_CONVERT_SCHEMA
from saki_ir.convert.io import load_yolo_dataset, save_yolo_dataset
from saki_ir.convert.yolo_obb import ir_to_yolo_obb_txt, yolo_obb_txt_to_ir
from saki_ir.geom import obb_to_vertices
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as ir


def _items_by_kind(batch: ir.DataBatchIR, kind: str):
    return [item for item in batch.items if item.WhichOneof("item") == kind]


def _sorted_vertices(obb: ir.ObbGeometry) -> list[tuple[float, float]]:
    return sorted((round(x, 3), round(y, 3)) for x, y in obb_to_vertices(obb))


def test_yolo_obb_rbox_normalized_deg_roundtrip() -> None:
    txt = "0 0.500000 0.500000 0.200000 0.100000 30.000000\n"
    ctx = ConversionContext(strict=True, yolo_is_normalized=True, yolo_obb_angle_unit="deg")

    batch = yolo_obb_txt_to_ir(
        txt,
        image_w=640,
        image_h=480,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ctx,
    )
    ann = _items_by_kind(batch, "annotation")[0].annotation
    obb = ann.geometry.obb

    assert obb.cx == pytest.approx(320.0, abs=1e-6)
    assert obb.cy == pytest.approx(240.0, abs=1e-6)
    assert obb.width == pytest.approx(128.0, abs=1e-6)
    assert obb.height == pytest.approx(48.0, abs=1e-6)
    assert obb.angle_deg_cw == pytest.approx(30.0, abs=1e-6)

    out = ir_to_yolo_obb_txt(
        batch,
        image_w=640,
        image_h=480,
        class_to_index={"car": 0},
        fmt="rbox",
        angle_unit="deg",
        ctx=ctx,
    )
    parts = out.split()
    assert parts[0] == "0"
    assert float(parts[1]) == pytest.approx(0.5, abs=1e-6)
    assert float(parts[2]) == pytest.approx(0.5, abs=1e-6)
    assert float(parts[3]) == pytest.approx(0.2, abs=1e-6)
    assert float(parts[4]) == pytest.approx(0.1, abs=1e-6)
    assert float(parts[5]) == pytest.approx(30.0, abs=1e-6)


def test_yolo_obb_angle_auto_infers_degree_for_common_degree_values() -> None:
    txt = "0 0.500000 0.500000 0.200000 0.100000 30.000000\n"
    ctx = ConversionContext(strict=True, yolo_is_normalized=True, yolo_obb_angle_unit="auto")
    batch = yolo_obb_txt_to_ir(
        txt,
        image_w=640,
        image_h=480,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ctx,
    )
    obb = _items_by_kind(batch, "annotation")[0].annotation.geometry.obb
    assert obb.angle_deg_cw == pytest.approx(30.0, abs=1e-6)


def test_yolo_obb_poly8_normalized_roundtrip() -> None:
    txt = "0 0.400000 0.400000 0.600000 0.400000 0.600000 0.500000 0.400000 0.500000\n"
    ctx = ConversionContext(strict=True, yolo_is_normalized=True, yolo_obb_angle_unit="auto")

    batch = yolo_obb_txt_to_ir(
        txt,
        image_w=100,
        image_h=100,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ctx,
    )

    ann = _items_by_kind(batch, "annotation")[0].annotation
    obb = ann.geometry.obb
    assert obb.cx == pytest.approx(50.0, abs=1e-6)
    assert obb.cy == pytest.approx(45.0, abs=1e-6)

    out = ir_to_yolo_obb_txt(
        batch,
        image_w=100,
        image_h=100,
        class_to_index={"car": 0},
        fmt="poly8",
        angle_unit="deg",
        ctx=ctx,
    )
    batch2 = yolo_obb_txt_to_ir(
        out,
        image_w=100,
        image_h=100,
        class_names=["car"],
        image_relpath="images/train/img1.jpg",
        ctx=ctx,
    )

    obb2 = _items_by_kind(batch2, "annotation")[0].annotation.geometry.obb
    assert _sorted_vertices(obb) == _sorted_vertices(obb2)


def test_yolo_obb_label_format_constraints() -> None:
    with pytest.raises(ConversionError) as exc:
        yolo_obb_txt_to_ir(
            "0 0.4 0.4 0.6 0.4 0.6 0.5 0.4 0.5\n",
            image_w=100,
            image_h=100,
            class_names=["car"],
            image_relpath="img.jpg",
            ctx=ConversionContext(strict=True, yolo_is_normalized=True, yolo_label_format="obb_rbox"),
        )
    assert exc.value.code == ERR_CONVERT_SCHEMA

    with pytest.raises(ConversionError) as exc:
        yolo_obb_txt_to_ir(
            "0 0.5 0.5 0.2 0.1 30\n",
            image_w=100,
            image_h=100,
            class_names=["car"],
            image_relpath="img.jpg",
            ctx=ConversionContext(strict=True, yolo_is_normalized=True, yolo_label_format="obb_poly8"),
        )
    assert exc.value.code == ERR_CONVERT_SCHEMA


def test_yolo_obb_missing_size_strict_and_lenient() -> None:
    txt = "0 0.5 0.5 0.2 0.1 30\n"

    with pytest.raises(ConversionError) as exc:
        yolo_obb_txt_to_ir(
            txt,
            image_w=None,
            image_h=None,
            class_names=["car"],
            image_relpath="a.jpg",
            ctx=ConversionContext(strict=True, yolo_is_normalized=True),
        )
    assert exc.value.code == ERR_CONVERT_SCHEMA

    report = ConversionReport()
    batch = yolo_obb_txt_to_ir(
        txt,
        image_w=None,
        image_h=None,
        class_names=["car"],
        image_relpath="a.jpg",
        ctx=ConversionContext(strict=False, yolo_is_normalized=True),
        report=report,
    )
    assert len(_items_by_kind(batch, "sample")) == 1
    assert len(_items_by_kind(batch, "annotation")) == 0
    assert report.errors


def test_yolo_obb_dataset_io_entry_switch(tmp_path: Path) -> None:
    batch = ir.DataBatchIR(
        items=[
            ir.DataItemIR(label=ir.LabelRecord(id="l1", name="car")),
            ir.DataItemIR(sample=ir.SampleRecord(id="s1", width=640, height=480)),
            ir.DataItemIR(
                annotation=ir.AnnotationRecord(
                    id="a1",
                    sample_id="s1",
                    label_id="l1",
                    confidence=1.0,
                    geometry=ir.Geometry(obb=ir.ObbGeometry(cx=200.0, cy=120.0, width=80.0, height=40.0, angle_deg_cw=25.0)),
                )
            ),
        ]
    )

    root = tmp_path / "yolo_obb"
    (root / "images" / "train").mkdir(parents=True)
    (root / "images" / "train" / "s1.jpg").write_bytes(
        bytes.fromhex(
            "89504E470D0A1A0A"
            "0000000D4948445200000001000000010802000000907753DE"
            "0000000C49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
    )

    save_yolo_dataset(
        batch,
        root,
        "train",
        ctx=ConversionContext(
            strict=True,
            naming="uuid",
            yolo_is_normalized=False,
            yolo_label_format="obb_rbox",
            yolo_obb_angle_unit="deg",
        ),
    )

    loaded = load_yolo_dataset(
        root,
        "train",
        ctx=ConversionContext(
            strict=True,
            yolo_is_normalized=False,
            yolo_label_format="obb_rbox",
            read_images=False,
        ),
    )

    samples = _items_by_kind(loaded, "sample")
    anns = _items_by_kind(loaded, "annotation")
    assert len(samples) == 1
    assert len(anns) == 1

    obb = anns[0].annotation.geometry.obb
    assert obb.cx == pytest.approx(200.0, abs=1e-3)
    assert obb.cy == pytest.approx(120.0, abs=1e-3)
    assert obb.width == pytest.approx(80.0, abs=1e-3)
    assert obb.height == pytest.approx(40.0, abs=1e-3)
    assert obb.angle_deg_cw == pytest.approx(25.0, abs=1e-3)
