from __future__ import annotations

import inspect
import uuid

import pytest
from pydantic import ValidationError

from saki_api.modules.importing.api.http.project_import import (
    dry_run_project_annotation_import,
    dry_run_project_associated_import,
)
from saki_api.modules.importing.schema import (
    AnnotationDryRunPayload,
    AssociatedDryRunPayload,
    ImportFormat,
)


def test_import_format_enum_contains_yolo_obb() -> None:
    assert ImportFormat.YOLO_OBB.value == "yolo_obb"


def test_project_import_http_dry_run_signature_uses_format_profile() -> None:
    annotation_params = inspect.signature(dry_run_project_annotation_import).parameters
    associated_params = inspect.signature(dry_run_project_associated_import).parameters

    assert "format_profile" in annotation_params
    assert "format" not in annotation_params

    assert "format_profile" in associated_params
    assert "format" not in associated_params


def test_annotation_dry_run_payload_requires_format_profile() -> None:
    with pytest.raises(ValidationError):
        AnnotationDryRunPayload.model_validate(
            {
                "dataset_id": str(uuid.uuid4()),
                "branch_name": "master",
            }
        )

    payload = AnnotationDryRunPayload.model_validate(
        {
            "format_profile": "yolo_obb",
            "dataset_id": str(uuid.uuid4()),
            "branch_name": "master",
        }
    )
    assert payload.format_profile == ImportFormat.YOLO_OBB


def test_associated_dry_run_payload_rejects_legacy_format_field() -> None:
    with pytest.raises(ValidationError):
        AssociatedDryRunPayload.model_validate(
            {
                "format": "yolo",
                "branch_name": "master",
                "target_dataset_mode": "existing",
                "target_dataset_id": str(uuid.uuid4()),
            }
        )

    payload = AssociatedDryRunPayload.model_validate(
        {
            "format_profile": "yolo",
            "branch_name": "master",
            "target_dataset_mode": "existing",
            "target_dataset_id": str(uuid.uuid4()),
        }
    )
    assert payload.format_profile == ImportFormat.YOLO
