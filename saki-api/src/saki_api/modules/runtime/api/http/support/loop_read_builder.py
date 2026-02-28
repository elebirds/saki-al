"""Loop read-model serializer helpers."""

from __future__ import annotations

from saki_api.modules.shared.modeling.enums import LoopStage
from saki_api.modules.runtime.api.round_step import LoopRead


def build_loop_read(*, loop, stage: LoopStage, stage_meta: dict) -> LoopRead:
    payload = loop.model_dump()
    payload["stage"] = stage
    payload["stage_meta"] = stage_meta
    return LoopRead.model_validate(payload)
