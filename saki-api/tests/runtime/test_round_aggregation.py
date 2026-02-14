from __future__ import annotations

import uuid

from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.service.application.round_aggregation import build_round_update_from_steps
from saki_api.modules.shared.modeling.enums import (
    LoopMode,
    RoundStatus,
    StepDispatchKind,
    StepStatus,
    StepType,
)


def test_active_learning_round_completed_maps_to_wait_user():
    project_id = uuid.uuid4()
    loop_id = uuid.uuid4()
    round_id = uuid.uuid4()
    round_row = Round(
        id=round_id,
        project_id=project_id,
        loop_id=loop_id,
        round_index=1,
        mode=LoopMode.ACTIVE_LEARNING,
        state=RoundStatus.RUNNING,
        step_counts={},
        round_type="loop_round",
        plugin_id="yolo_det_v1",
        query_strategy="random_baseline",
        resolved_params={},
        resources={},
        final_metrics={},
        final_artifacts={},
    )
    steps = [
        Step(
            id=uuid.uuid4(),
            round_id=round_id,
            step_type=StepType.TRAIN,
            dispatch_kind=StepDispatchKind.DISPATCHABLE,
            state=StepStatus.SUCCEEDED,
            round_index=1,
            step_index=1,
            depends_on_step_ids=[],
            resolved_params={},
            metrics={},
            artifacts={},
            attempt=1,
            max_attempts=3,
        ),
        Step(
            id=uuid.uuid4(),
            round_id=round_id,
            step_type=StepType.SELECT,
            dispatch_kind=StepDispatchKind.ORCHESTRATOR,
            state=StepStatus.SUCCEEDED,
            round_index=1,
            step_index=2,
            depends_on_step_ids=[],
            resolved_params={},
            metrics={},
            artifacts={},
            attempt=1,
            max_attempts=3,
        ),
    ]

    update = build_round_update_from_steps(round_row=round_row, steps=steps)
    assert update.state == RoundStatus.WAIT_USER
    assert update.ended_at is not None
