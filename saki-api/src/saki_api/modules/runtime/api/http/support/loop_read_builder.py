"""Loop read-model serializer helpers."""

from __future__ import annotations

from saki_api.modules.runtime.api.round_step import LoopRead
from saki_api.modules.runtime.service.config.loop_config_service import (
    extract_model_request_config,
    extract_simulation_config,
)


def build_loop_read(loop) -> LoopRead:
    row = LoopRead.model_validate(loop, from_attributes=True)
    return row.model_copy(
        update={
            "model_request_config": extract_model_request_config(getattr(loop, "global_config", {})),
            "simulation_config": extract_simulation_config(getattr(loop, "global_config", {})),
        }
    )
