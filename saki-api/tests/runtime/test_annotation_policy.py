from __future__ import annotations

import pytest

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.project.domain.annotation_policy import (
    assert_annotation_type_enabled,
    validate_dataset_link_compatibility,
    validate_project_creation_policy,
)
from saki_api.modules.shared.modeling.enums import AnnotationType, DatasetType, TaskType
from saki_api.modules.system.service.system import SystemService


def test_validate_project_creation_policy_detection_classic_success() -> None:
    enabled = validate_project_creation_policy(
        task_type=TaskType.DETECTION,
        enabled_types=[AnnotationType.RECT],
        dataset_types=[DatasetType.CLASSIC],
    )
    assert enabled == [AnnotationType.RECT]


def test_validate_project_creation_policy_detection_fedo_requires_obb() -> None:
    with pytest.raises(BadRequestAppException, match="requires obb enabled"):
        validate_project_creation_policy(
            task_type=TaskType.DETECTION,
            enabled_types=[AnnotationType.RECT],
            dataset_types=[DatasetType.FEDO],
        )


def test_validate_project_creation_policy_detection_fedo_with_obb_success() -> None:
    enabled = validate_project_creation_policy(
        task_type=TaskType.DETECTION,
        enabled_types=[AnnotationType.OBB],
        dataset_types=[DatasetType.FEDO],
    )
    assert enabled == [AnnotationType.OBB]


def test_validate_project_creation_policy_rejects_unsupported_task() -> None:
    with pytest.raises(BadRequestAppException, match="task_type not supported"):
        validate_project_creation_policy(
            task_type=TaskType.CLASSIFICATION,
            enabled_types=[AnnotationType.RECT],
            dataset_types=[DatasetType.CLASSIC],
        )


def test_validate_dataset_link_compatibility_requires_obb_for_fedo() -> None:
    with pytest.raises(BadRequestAppException, match="requires obb enabled"):
        validate_dataset_link_compatibility(
            project_enabled_types=[AnnotationType.RECT],
            dataset_type=DatasetType.FEDO,
        )


def test_assert_annotation_type_enabled_fails_for_disabled_type() -> None:
    with pytest.raises(BadRequestAppException, match="annotation type rect is not enabled"):
        assert_annotation_type_enabled(
            project_enabled_types=[AnnotationType.OBB],
            ann_type=AnnotationType.RECT,
        )


def test_system_types_expose_annotation_policy_fields() -> None:
    payload = SystemService.get_available_types()
    detection = next(item for item in payload["task"] if item["value"] == "detection")
    fedo = next(item for item in payload["dataset"] if item["value"] == "fedo")
    assert detection["enabled"] is True
    assert set(detection["allowed_annotation_types"]) == {"rect", "obb"}
    assert detection["must_annotation_types"] == []
    assert detection["banned_annotation_types"] == []
    assert fedo["allowed_annotation_types"] == []
    assert fedo["must_annotation_types"] == ["obb"]
    assert fedo["banned_annotation_types"] == []
