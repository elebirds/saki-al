from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from saki_ir import parse_geometry
from saki_ir.quad8 import geometry_to_quad8_local

from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.project.api.export import PredictionsJSONOptions
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.service.predictions_json_filter import filter_predictions_json_annotations


@dataclass(slots=True, frozen=True)
class PredictionsJSONEntryInput:
    sample_id: uuid.UUID
    dataset_id: uuid.UUID
    image_path: str


@dataclass(slots=True, frozen=True)
class PredictionsJSONTraceContext:
    annotation_commit_id: uuid.UUID | None = None
    branch_name: str | None = None
    exported_at: datetime | None = None


def build_predictions_json_entries(
    *,
    entry_inputs: list[PredictionsJSONEntryInput],
    annotations_by_sample: dict[uuid.UUID, list[Annotation]],
    labels: list[Label],
    options: PredictionsJSONOptions,
    trace_context: PredictionsJSONTraceContext,
) -> tuple[list[dict[str, Any]], list[str]]:
    ordered_labels = sorted(
        labels,
        key=lambda item: (int(item.sort_order or 0), str(item.id)),
    )
    class_id_by_label_id = {label.id: index for index, label in enumerate(ordered_labels)}
    label_by_id = {label.id: label for label in labels}
    label_name_by_id = {label.id: str(label.name) for label in labels}

    entries: list[dict[str, Any]] = []
    issues: list[str] = []

    for entry_input in entry_inputs:
        detections: list[dict[str, Any]] = []
        filtered_annotations = filter_predictions_json_annotations(
            annotations=annotations_by_sample.get(entry_input.sample_id, []),
            label_name_by_id=label_name_by_id,
            filter_node=options.filter,
        )
        for annotation in filtered_annotations:
            label = label_by_id.get(annotation.label_id)
            class_id = class_id_by_label_id.get(annotation.label_id)
            if label is None or class_id is None:
                issues.append(
                    f"sample={entry_input.sample_id} annotation={annotation.id} label not found: {annotation.label_id}"
                )
                continue
            try:
                detections.append(
                    _build_detection(
                        annotation=annotation,
                        label=label,
                        class_id=class_id,
                        options=options,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    f"sample={entry_input.sample_id} annotation={annotation.id} predictions_json serialization failed: {exc}"
                )

        if not detections and not options.include_empty_entries:
            continue

        entry = {
            "image_path": entry_input.image_path,
            "detections": detections,
        }
        _append_entry_trace_fields(entry, entry_input=entry_input, trace_context=trace_context, options=options)
        entries.append(entry)

    return entries, issues


def _build_detection(
    *,
    annotation: Annotation,
    label: Label,
    class_id: int,
    options: PredictionsJSONOptions,
) -> dict[str, Any]:
    geometry_payload = copy.deepcopy(dict(annotation.geometry or {}))
    geometry_proto = parse_geometry(geometry_payload)
    annotation_type = annotation.type.value if hasattr(annotation.type, "value") else str(annotation.type)
    geometry_shape = geometry_proto.WhichOneof("shape")
    if geometry_shape != annotation_type:
        raise ValueError(f"annotation type mismatch: annotation.type={annotation_type}, geometry={geometry_shape}")

    detection: dict[str, Any] = {
        "annotation_type": annotation_type,
        "class_id": class_id,
        "class_name": str(label.name),
        "confidence": float(annotation.confidence),
        "geometry": geometry_payload,
    }
    _append_detection_trace_fields(detection, annotation=annotation, options=options)

    if annotation_type == "rect":
        rect = geometry_payload["rect"]
        x = float(rect["x"])
        y = float(rect["y"])
        width = float(rect["width"])
        height = float(rect["height"])
        if "xyxy" in set(options.geometry_compat_fields.rect):
            detection["xyxy"] = [x, y, x + width, y + height]
        if "xywh" in set(options.geometry_compat_fields.rect):
            detection["xywh"] = [x, y, width, height]
        return detection

    if annotation_type == "obb":
        obb = geometry_payload["obb"]
        quad8 = list(geometry_to_quad8_local(geometry_payload))
        if "xyxyxyxy" in set(options.geometry_compat_fields.obb):
            detection["xyxyxyxy"] = quad8
        if "xywhr" in set(options.geometry_compat_fields.obb):
            detection["xywhr"] = [
                float(obb["cx"]),
                float(obb["cy"]),
                float(obb["width"]),
                float(obb["height"]),
                math.radians(float(obb["angle_deg_ccw"])),
            ]
        return detection

    raise ValueError(f"unsupported annotation_type={annotation_type}")


def _append_entry_trace_fields(
    entry: dict[str, Any],
    *,
    entry_input: PredictionsJSONEntryInput,
    trace_context: PredictionsJSONTraceContext,
    options: PredictionsJSONOptions,
) -> None:
    requested = set(options.include_entry_trace_fields)
    if "sample_id" in requested:
        entry["sample_id"] = str(entry_input.sample_id)
    if "dataset_id" in requested:
        entry["dataset_id"] = str(entry_input.dataset_id)
    if "annotation_commit_id" in requested and trace_context.annotation_commit_id is not None:
        entry["annotation_commit_id"] = str(trace_context.annotation_commit_id)
    if "branch_name" in requested and trace_context.branch_name is not None:
        entry["branch_name"] = trace_context.branch_name
    if "exported_at" in requested and trace_context.exported_at is not None:
        entry["exported_at"] = trace_context.exported_at.isoformat()


def _append_detection_trace_fields(
    detection: dict[str, Any],
    *,
    annotation: Annotation,
    options: PredictionsJSONOptions,
) -> None:
    requested = set(options.include_detection_trace_fields)
    if "annotation_id" in requested:
        detection["annotation_id"] = str(annotation.id)
    if "label_id" in requested:
        detection["label_id"] = str(annotation.label_id)
    if "source" in requested:
        detection["source"] = annotation.source.value if hasattr(annotation.source, "value") else str(annotation.source)
    if "attrs" in requested:
        detection["attrs"] = copy.deepcopy(dict(annotation.attrs or {}))
