from __future__ import annotations

import uuid

from saki_api.infra.grpc.runtime_control import RuntimeDomainService
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.shared.modeling.enums import RuntimeTaskKind, RuntimeTaskStatus, RuntimeTaskType


def _make_task(*, resolved_params: dict) -> Task:
    return Task(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        kind=RuntimeTaskKind.STEP,
        task_type=RuntimeTaskType.TRAIN,
        status=RuntimeTaskStatus.SUCCEEDED,
        plugin_id="yolo_det_v1",
        resolved_params=resolved_params,
        attempt=1,
        max_attempts=3,
    )


def test_resolve_result_artifact_uri_from_task_reads_task_result_artifacts():
    task = _make_task(
        resolved_params={
            "_result_artifacts": {
                "best.pt": {
                    "kind": "weights",
                    "uri": "https://example.com/models/best.pt",
                    "meta": {},
                }
            }
        }
    )
    found, uri = RuntimeDomainService._resolve_result_artifact_uri_from_task(
        task=task,
        artifact_name="best.pt",
    )
    assert found is True
    assert uri == "https://example.com/models/best.pt"


def test_resolve_result_artifact_uri_from_task_handles_missing_or_empty_uri():
    missing_task = _make_task(resolved_params={"_result_artifacts": {}})
    found_missing, uri_missing = RuntimeDomainService._resolve_result_artifact_uri_from_task(
        task=missing_task,
        artifact_name="best.pt",
    )
    assert found_missing is False
    assert uri_missing == ""

    empty_uri_task = _make_task(
        resolved_params={
            "_result_artifacts": {
                "best.pt": {
                    "kind": "weights",
                    "uri": "",
                    "meta": {},
                }
            }
        }
    )
    found_empty, uri_empty = RuntimeDomainService._resolve_result_artifact_uri_from_task(
        task=empty_uri_task,
        artifact_name="best.pt",
    )
    assert found_empty is True
    assert uri_empty == ""
