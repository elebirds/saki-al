from __future__ import annotations

import inspect
import uuid

import pytest
from pydantic import ValidationError

from saki_api.modules.importing.api.http.project_import import (
    prepare_project_annotation_import,
    prepare_project_associated_import,
)
from saki_api.modules.importing.schema import (
    ImportFormat,
    ProjectAnnotationImportPrepareRequest,
    ProjectAssociatedImportPrepareRequest,
)


def test_import_format_enum_contains_yolo_obb() -> None:
    assert ImportFormat.YOLO_OBB.value == "yolo_obb"
    assert ImportFormat.DOTA.value == "dota"


def test_project_import_http_prepare_signature_uses_payload_model() -> None:
    annotation_params = inspect.signature(prepare_project_annotation_import).parameters
    associated_params = inspect.signature(prepare_project_associated_import).parameters

    assert "payload" in annotation_params
    assert "format_profile" not in annotation_params
    assert "format" not in annotation_params

    assert "payload" in associated_params
    assert "format_profile" not in associated_params
    assert "format" not in associated_params


def test_annotation_prepare_payload_requires_format_profile() -> None:
    with pytest.raises(ValidationError):
        ProjectAnnotationImportPrepareRequest.model_validate(
            {
                "upload_session_id": str(uuid.uuid4()),
                "dataset_id": str(uuid.uuid4()),
                "branch_name": "master",
            }
        )

    payload = ProjectAnnotationImportPrepareRequest.model_validate(
        {
            "upload_session_id": str(uuid.uuid4()),
            "format_profile": "yolo_obb",
            "dataset_id": str(uuid.uuid4()),
            "branch_name": "master",
        }
    )
    assert payload.format_profile == ImportFormat.YOLO_OBB


def test_associated_prepare_payload_rejects_legacy_format_field() -> None:
    with pytest.raises(ValidationError):
        ProjectAssociatedImportPrepareRequest.model_validate(
            {
                "upload_session_id": str(uuid.uuid4()),
                "format": "yolo",
                "branch_name": "master",
                "target_dataset_mode": "existing",
                "target_dataset_id": str(uuid.uuid4()),
            }
        )

    payload = ProjectAssociatedImportPrepareRequest.model_validate(
        {
            "upload_session_id": str(uuid.uuid4()),
            "format_profile": "yolo",
            "branch_name": "master",
            "target_dataset_mode": "existing",
            "target_dataset_id": str(uuid.uuid4()),
        }
    )
    assert payload.format_profile == ImportFormat.YOLO
