"""Backward compatibility alias for Round model."""

from saki_api.modules.runtime.domain.round import Round as Job
from saki_api.modules.runtime.domain.round import RoundBase as JobBase

__all__ = ["Job", "JobBase"]
