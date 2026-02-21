"""Loop read-model serializer helpers."""

from __future__ import annotations

from saki_api.modules.runtime.api.round_step import LoopRead


def build_loop_read(loop) -> LoopRead:
    return LoopRead.model_validate(loop, from_attributes=True)
