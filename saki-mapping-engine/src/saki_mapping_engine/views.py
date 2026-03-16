from __future__ import annotations

from enum import Enum


class FedoView(str, Enum):
    TIME_ENERGY = "time-energy"
    L_OMEGAD = "L-omegad"

    @classmethod
    def parse(cls, value: str | "FedoView") -> "FedoView":
        if isinstance(value, cls):
            return value
        return cls(value)
