from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from saki_ir.quad8 import geometry_to_quad8_local

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.project.api.export import (
    PredictionsJSONFilterGroup,
    PredictionsJSONFilterRule,
    PredictionsJSONOptions,
)
from saki_api.modules.project.service.predictions_json_export import (
    PredictionsJSONEntryInput,
    PredictionsJSONTraceContext,
    build_predictions_json_entries,
)
from saki_api.modules.project.service.predictions_json_filter import (
    filter_predictions_json_annotations,
)
from saki_api.modules.shared.modeling.enums import AnnotationSource, AnnotationType


@dataclass(slots=True)
class _FakeLabel:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    color: str
    sort_order: int


@dataclass(slots=True)
class _FakeAnnotation:
    id: uuid.UUID
    sample_id: uuid.UUID
    project_id: uuid.UUID
    label_id: uuid.UUID
    group_id: uuid.UUID
    lineage_id: uuid.UUID
    type: AnnotationType
    source: AnnotationSource
    confidence: float
    geometry: dict
    attrs: dict


def _make_label(*, name: str, sort_order: int) -> _FakeLabel:
    return _FakeLabel(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name=name,
        color="#ff0000",
        sort_order=sort_order,
    )


def _make_annotation(
    *,
    sample_id: uuid.UUID,
    project_id: uuid.UUID,
    label_id: uuid.UUID,
    ann_type: AnnotationType,
    source: AnnotationSource,
    confidence: float,
    geometry: dict,
    attrs: dict | None = None,
) -> _FakeAnnotation:
    return _FakeAnnotation(
        id=uuid.uuid4(),
        sample_id=sample_id,
        project_id=project_id,
        label_id=label_id,
        group_id=uuid.uuid4(),
        lineage_id=uuid.uuid4(),
        type=ann_type,
        source=source,
        confidence=confidence,
        geometry=geometry,
        attrs=attrs or {},
    )


def test_filter_matches_annotation_source_and_confidence():
    sample_id = uuid.uuid4()
    project_id = uuid.uuid4()
    label = _make_label(name="car", sort_order=1)
    matched = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.91,
        geometry={"rect": {"x": 10, "y": 12, "width": 30, "height": 20}},
    )
    rejected = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MANUAL,
        confidence=0.72,
        geometry={"rect": {"x": 5, "y": 6, "width": 10, "height": 12}},
    )

    filter_node = PredictionsJSONFilterGroup(
        op="and",
        items=[
            PredictionsJSONFilterRule(
                field="annotation.source",
                operator="in",
                value=["model", "confirmed_model"],
            ),
            PredictionsJSONFilterRule(
                field="annotation.confidence",
                operator="gte",
                value=0.8,
            ),
        ],
    )

    filtered = filter_predictions_json_annotations(
        annotations=[matched, rejected],
        label_name_by_id={label.id: label.name},
        filter_node=filter_node,
    )

    assert [item.id for item in filtered] == [matched.id]


def test_filter_reads_annotation_attrs_path():
    sample_id = uuid.uuid4()
    project_id = uuid.uuid4()
    label = _make_label(name="car", sort_order=1)
    matched = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.9,
        geometry={"rect": {"x": 10, "y": 10, "width": 20, "height": 10}},
        attrs={"export": {"tag": "partner_a", "score": 7}},
    )
    rejected = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.9,
        geometry={"rect": {"x": 15, "y": 16, "width": 10, "height": 8}},
        attrs={"export": {"tag": "partner_b", "score": 4}},
    )

    filter_node = PredictionsJSONFilterGroup(
        op="and",
        items=[
            PredictionsJSONFilterRule(
                field="annotation.attrs.export.tag",
                operator="eq",
                value="partner_a",
            ),
            PredictionsJSONFilterRule(
                field="annotation.attrs.export.score",
                operator="gt",
                value=5,
            ),
        ],
    )

    filtered = filter_predictions_json_annotations(
        annotations=[matched, rejected],
        label_name_by_id={label.id: label.name},
        filter_node=filter_node,
    )

    assert [item.id for item in filtered] == [matched.id]


def test_filter_rejects_unknown_field():
    annotation = _make_annotation(
        sample_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        label_id=uuid.uuid4(),
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.5,
        geometry={"rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
    )

    with pytest.raises(BadRequestAppException, match="annotation.sample_id"):
        filter_predictions_json_annotations(
            annotations=[annotation],
            label_name_by_id={},
            filter_node=PredictionsJSONFilterRule(
                field="annotation.sample_id",
                operator="eq",
                value=str(annotation.sample_id),
            ),
        )


def test_filter_rejects_invalid_in_value_type():
    annotation = _make_annotation(
        sample_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        label_id=uuid.uuid4(),
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.5,
        geometry={"rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
    )

    with pytest.raises(BadRequestAppException, match="operator=in"):
        filter_predictions_json_annotations(
            annotations=[annotation],
            label_name_by_id={},
            filter_node=PredictionsJSONFilterRule(
                field="annotation.source",
                operator="in",
                value="model",
            ),
        )


def test_rect_detection_emits_geometry_and_xyxy_xywh():
    sample_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    project_id = uuid.uuid4()
    car = _make_label(name="car", sort_order=2)
    bus = _make_label(name="bus", sort_order=1)
    annotation = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=car.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MODEL,
        confidence=0.92,
        geometry={"rect": {"x": 10, "y": 12, "width": 30, "height": 20}},
    )

    entries, issues = build_predictions_json_entries(
        entry_inputs=[
            PredictionsJSONEntryInput(
                sample_id=sample_id,
                dataset_id=dataset_id,
                image_path="images/train/sample-1.jpg",
            )
        ],
        annotations_by_sample={sample_id: [annotation]},
        labels=[car, bus],
        options=PredictionsJSONOptions(),
        trace_context=PredictionsJSONTraceContext(),
    )

    assert issues == []
    assert len(entries) == 1
    assert entries[0]["image_path"] == "images/train/sample-1.jpg"
    assert len(entries[0]["detections"]) == 1

    detection = entries[0]["detections"][0]
    assert detection == {
        "annotation_type": "rect",
        "class_id": 1,
        "class_name": "car",
        "confidence": 0.92,
        "geometry": {"rect": {"x": 10, "y": 12, "width": 30, "height": 20}},
        "xyxy": [10.0, 12.0, 40.0, 32.0],
        "xywh": [10.0, 12.0, 30.0, 20.0],
    }


def test_obb_detection_emits_geometry_and_xyxyxyxy_xywhr():
    sample_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    project_id = uuid.uuid4()
    pattern = _make_label(name="pattern", sort_order=1)
    geometry = {
        "obb": {
            "cx": 50,
            "cy": 40,
            "width": 30,
            "height": 20,
            "angle_deg_ccw": 10,
        }
    }
    annotation = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=pattern.id,
        ann_type=AnnotationType.OBB,
        source=AnnotationSource.MODEL,
        confidence=0.86,
        geometry=geometry,
    )

    entries, issues = build_predictions_json_entries(
        entry_inputs=[
            PredictionsJSONEntryInput(
                sample_id=sample_id,
                dataset_id=dataset_id,
                image_path="images/train/sample-2.jpg",
            )
        ],
        annotations_by_sample={sample_id: [annotation]},
        labels=[pattern],
        options=PredictionsJSONOptions(),
        trace_context=PredictionsJSONTraceContext(),
    )

    assert issues == []
    detection = entries[0]["detections"][0]
    assert detection["annotation_type"] == "obb"
    assert detection["class_id"] == 0
    assert detection["class_name"] == "pattern"
    assert detection["confidence"] == 0.86
    assert detection["geometry"] == geometry
    assert detection["xyxyxyxy"] == list(geometry_to_quad8_local(geometry))
    assert detection["xywhr"] == pytest.approx([50.0, 40.0, 30.0, 20.0, math.radians(10)])


def test_include_empty_entries_keeps_empty_sample_entry():
    sample_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    project_id = uuid.uuid4()
    label = _make_label(name="car", sort_order=1)
    annotation = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.MANUAL,
        confidence=0.95,
        geometry={"rect": {"x": 10, "y": 12, "width": 30, "height": 20}},
    )

    entries, issues = build_predictions_json_entries(
        entry_inputs=[
            PredictionsJSONEntryInput(
                sample_id=sample_id,
                dataset_id=dataset_id,
                image_path="images/train/sample-3.jpg",
            )
        ],
        annotations_by_sample={sample_id: [annotation]},
        labels=[label],
        options=PredictionsJSONOptions(
            include_empty_entries=True,
            filter=PredictionsJSONFilterRule(
                field="annotation.source",
                operator="eq",
                value="model",
            ),
        ),
        trace_context=PredictionsJSONTraceContext(),
    )

    assert issues == []
    assert entries == [
        {
            "image_path": "images/train/sample-3.jpg",
            "detections": [],
        }
    ]


def test_entry_and_detection_include_requested_trace_fields():
    sample_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    commit_id = uuid.uuid4()
    project_id = uuid.uuid4()
    label = _make_label(name="car", sort_order=1)
    annotation = _make_annotation(
        sample_id=sample_id,
        project_id=project_id,
        label_id=label.id,
        ann_type=AnnotationType.RECT,
        source=AnnotationSource.CONFIRMED_MODEL,
        confidence=0.97,
        geometry={"rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
        attrs={"export_tag": "partner_a"},
    )
    exported_at = datetime(2026, 3, 17, 12, 34, 56, tzinfo=timezone.utc)

    entries, issues = build_predictions_json_entries(
        entry_inputs=[
            PredictionsJSONEntryInput(
                sample_id=sample_id,
                dataset_id=dataset_id,
                image_path="images/train/sample-4.jpg",
            )
        ],
        annotations_by_sample={sample_id: [annotation]},
        labels=[label],
        options=PredictionsJSONOptions(
            include_entry_trace_fields=[
                "sample_id",
                "dataset_id",
                "annotation_commit_id",
                "branch_name",
                "exported_at",
            ],
            include_detection_trace_fields=[
                "annotation_id",
                "label_id",
                "source",
                "attrs",
            ],
        ),
        trace_context=PredictionsJSONTraceContext(
            annotation_commit_id=commit_id,
            branch_name="master",
            exported_at=exported_at,
        ),
    )

    assert issues == []
    assert entries == [
        {
            "image_path": "images/train/sample-4.jpg",
            "detections": [
                {
                    "annotation_type": "rect",
                    "class_id": 0,
                    "class_name": "car",
                    "confidence": 0.97,
                    "geometry": {"rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
                    "xyxy": [1.0, 2.0, 4.0, 6.0],
                    "xywh": [1.0, 2.0, 3.0, 4.0],
                    "annotation_id": str(annotation.id),
                    "label_id": str(label.id),
                    "source": "confirmed_model",
                    "attrs": {"export_tag": "partner_a"},
                }
            ],
            "sample_id": str(sample_id),
            "dataset_id": str(dataset_id),
            "annotation_commit_id": str(commit_id),
            "branch_name": "master",
            "exported_at": exported_at.isoformat(),
        }
    ]
