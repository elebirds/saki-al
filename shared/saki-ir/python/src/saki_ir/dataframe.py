from __future__ import annotations

from google.protobuf.json_format import MessageToDict

from saki_ir.errors import ERR_IR_DATAFRAME_UNAVAILABLE, ERR_IR_SCHEMA, IRError
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1


def _source_name(value: int) -> str:
    try:
        return annotationirv1.AnnotationSource.Name(value)
    except ValueError:
        return str(value)


def _to_annotation_rows(batch: annotationirv1.DataBatchIR) -> tuple[list[dict[str, object]], list[str]]:
    columns = [
        "id",
        "sample_id",
        "label_id",
        "source",
        "confidence",
        "shape",
        "rect_x",
        "rect_y",
        "rect_w",
        "rect_h",
        "obb_cx",
        "obb_cy",
        "obb_w",
        "obb_h",
        "obb_angle_deg_ccw",
    ]
    rows: list[dict[str, object]] = []

    for item in batch.items:
        if item.WhichOneof("item") != "annotation":
            continue

        ann = item.annotation
        row: dict[str, object] = {
            "id": ann.id,
            "sample_id": ann.sample_id,
            "label_id": ann.label_id,
            "source": _source_name(ann.source),
            "confidence": float(ann.confidence),
            "shape": None,
            "rect_x": None,
            "rect_y": None,
            "rect_w": None,
            "rect_h": None,
            "obb_cx": None,
            "obb_cy": None,
            "obb_w": None,
            "obb_h": None,
            "obb_angle_deg_ccw": None,
        }

        if ann.HasField("geometry"):
            shape = ann.geometry.WhichOneof("shape")
            row["shape"] = shape
            if shape == "rect":
                rect = ann.geometry.rect
                row["rect_x"] = float(rect.x)
                row["rect_y"] = float(rect.y)
                row["rect_w"] = float(rect.width)
                row["rect_h"] = float(rect.height)
            elif shape == "obb":
                obb = ann.geometry.obb
                row["obb_cx"] = float(obb.cx)
                row["obb_cy"] = float(obb.cy)
                row["obb_w"] = float(obb.width)
                row["obb_h"] = float(obb.height)
                row["obb_angle_deg_ccw"] = float(obb.angle_deg_ccw)

        rows.append(row)

    return rows, columns


def _to_sample_rows(batch: annotationirv1.DataBatchIR) -> tuple[list[dict[str, object]], list[str]]:
    columns = ["id", "asset_hash", "download_url", "width", "height", "meta"]
    rows: list[dict[str, object]] = []

    for item in batch.items:
        if item.WhichOneof("item") != "sample":
            continue
        sample = item.sample
        rows.append(
            {
                "id": sample.id,
                "asset_hash": sample.asset_hash,
                "download_url": sample.download_url,
                "width": int(sample.width),
                "height": int(sample.height),
                "meta": MessageToDict(sample.meta) if sample.HasField("meta") else {},
            }
        )

    return rows, columns


def _to_label_rows(batch: annotationirv1.DataBatchIR) -> tuple[list[dict[str, object]], list[str]]:
    columns = ["id", "name", "color"]
    rows: list[dict[str, object]] = []

    for item in batch.items:
        if item.WhichOneof("item") != "label":
            continue
        label = item.label
        rows.append({"id": label.id, "name": label.name, "color": label.color})

    return rows, columns


def to_dataframe(batch: annotationirv1.DataBatchIR, kind: str = "annotation"):
    """导出为 pandas.DataFrame。"""

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise IRError(ERR_IR_DATAFRAME_UNAVAILABLE, "未安装 pandas，无法导出 DataFrame") from exc

    if kind == "annotation":
        rows, columns = _to_annotation_rows(batch)
    elif kind == "sample":
        rows, columns = _to_sample_rows(batch)
    elif kind == "label":
        rows, columns = _to_label_rows(batch)
    else:
        raise IRError(ERR_IR_SCHEMA, f"未知 kind: {kind}")

    return pd.DataFrame(rows, columns=columns)
