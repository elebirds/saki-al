from __future__ import annotations

from dataclasses import dataclass
import io

import numpy as np


@dataclass(slots=True)
class LookupTable:
    n_time: int
    n_energy: int
    lut_te: np.ndarray
    lut_lw: np.ndarray


def load_lookup_table_from_bytes(data: bytes) -> LookupTable:
    buf = io.BytesIO(data)
    with np.load(buf) as npz:
        return LookupTable(
            n_time=int(npz["n_time"]),
            n_energy=int(npz["n_energy"]),
            lut_te=npz["lut_te"],
            lut_lw=npz["lut_lw"],
        )
