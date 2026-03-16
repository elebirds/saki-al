from __future__ import annotations

import base64
import io

import numpy as np

from saki_mapping_engine.fedo_mapper import map_fedo_obb


def _make_lookup_table_bytes() -> bytes:
    grid = np.arange(5, dtype=np.float32) * 10.0
    lut_te = np.zeros((5, 5, 2), dtype=np.float32)
    for row, y in enumerate(grid):
        for col, x in enumerate(grid):
            lut_te[row, col] = [x, y]
    lut_lw = lut_te + np.array([100.0, 200.0], dtype=np.float32)

    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        n_time=5,
        n_energy=5,
        lut_te=lut_te,
        lut_lw=lut_lw,
    )
    buf.seek(0)
    return buf.read()


def test_map_fedo_obb_uses_lookup_and_view_pair() -> None:
    result = map_fedo_obb(
        {
            "source_view": "time-energy",
            "target_view": "L-omegad",
            "source_geometry": {
                "rect": {
                    "x": 4.0,
                    "y": 4.0,
                    "width": 32.0,
                    "height": 32.0,
                }
            },
            "lookup_table_b64": base64.b64encode(_make_lookup_table_bytes()).decode("ascii"),
            "time_gap_threshold": 8,
        }
    )

    assert len(result["mapped_geometries"]) == 1
    geometry = result["mapped_geometries"][0]
    rect = geometry.get("rect")
    obb = geometry.get("obb")
    assert isinstance(rect, dict) or isinstance(obb, dict)

    if isinstance(rect, dict):
        assert rect["x"] >= 100.0
        assert rect["y"] >= 200.0
        assert rect["width"] > 0.0
        assert rect["height"] > 0.0
    else:
        assert obb["cx"] >= 100.0
        assert obb["cy"] >= 200.0
        assert obb["width"] > 0.0
        assert obb["height"] > 0.0
