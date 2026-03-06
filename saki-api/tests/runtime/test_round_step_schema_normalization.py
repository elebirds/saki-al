from __future__ import annotations

import uuid
from datetime import datetime, timezone

from saki_api.modules.runtime.api.round_step import StepRead


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_step_read_normalizes_none_json_fields() -> None:
    now = _now()
    payload = {
        "id": uuid.uuid4(),
        "round_id": uuid.uuid4(),
        "step_type": "train",
        "dispatch_kind": "dispatchable",
        "state": "pending",
        "round_index": 1,
        "step_index": 1,
        "depends_on_step_ids": None,
        "resolved_params": None,
        "metrics": None,
        "artifacts": None,
        "input_commit_id": None,
        "task_id": uuid.uuid4(),
        "assigned_executor_id": None,
        "attempt": 1,
        "max_attempts": 1,
        "started_at": None,
        "ended_at": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
    }

    model = StepRead.model_validate(payload)

    assert model.depends_on_step_ids == []
    assert model.resolved_params == {}
    assert model.metrics == {}
    assert model.artifacts == {}
    assert model.task_id == payload["task_id"]
