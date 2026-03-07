"""Loop read-model serializer helpers."""

from __future__ import annotations

from saki_api.modules.shared.modeling.enums import LoopGate
from saki_api.modules.runtime.api.round_step import LoopRead


def build_loop_read(*, loop, gate: LoopGate, gate_meta: dict) -> LoopRead:
    payload = loop.model_dump()
    payload["gate"] = gate
    payload["gate_meta"] = gate_meta
    return LoopRead.model_validate(payload)
