from __future__ import annotations

import base64
from typing import Any

import numpy as np
from saki_ir import geometry_to_quad8_local, quad8_to_aabb_rect, quad8_to_obb_payload

from saki_mapping_engine.lookup import LookupTable, load_lookup_table_from_bytes
from saki_mapping_engine.obb_mapper import map_obb_annotations
from saki_mapping_engine.views import FedoView


def map_fedo_obb(payload: dict[str, Any]) -> dict[str, Any]:
    geometry = payload.get("source_geometry")
    if not isinstance(geometry, dict):
        return {"mapped_geometries": []}

    lookup_table = _load_lookup_table(payload)
    source_view = _resolve_source_view(payload)
    target_view = _resolve_target_view(payload, source_view=source_view)
    src_vertices = _geometry_to_vertices(geometry)
    lut_src, lut_dst = _select_lut_pair(
        lookup_table,
        source_view=source_view,
        target_view=target_view,
    )
    mapped_vertices_list = map_obb_annotations(
        src_obb_vertices=src_vertices,
        lut_src=lut_src,
        lut_dst=lut_dst,
        time_gap_threshold=int(payload.get("time_gap_threshold", 50)),
        debug_output_dir=None,
    )

    mapped_geometries: list[dict[str, Any]] = []
    for vertices in mapped_vertices_list:
        mapped_geometry = _obb_vertices_to_geometry(vertices)
        mapped_geometries.append(_maybe_convert_to_rect(mapped_geometry))
    return {"mapped_geometries": mapped_geometries}


def _load_lookup_table(payload: dict[str, Any]) -> LookupTable:
    raw = payload.get("lookup_table_b64")
    if not isinstance(raw, str) or not raw:
        raise ValueError("lookup_table_b64 is required")
    return load_lookup_table_from_bytes(base64.b64decode(raw))


def _resolve_source_view(payload: dict[str, Any]) -> FedoView:
    raw = payload.get("source_view")
    if not isinstance(raw, str) or not raw:
        raise ValueError("source_view is required")
    return FedoView.parse(raw)


def _resolve_target_view(payload: dict[str, Any], *, source_view: FedoView) -> FedoView:
    raw = payload.get("target_view")
    if isinstance(raw, str) and raw:
        return FedoView.parse(raw)
    if source_view == FedoView.TIME_ENERGY:
        return FedoView.L_OMEGAD
    return FedoView.TIME_ENERGY


def _select_lut_pair(
    lookup: LookupTable,
    *,
    source_view: FedoView,
    target_view: FedoView,
) -> tuple[np.ndarray, np.ndarray]:
    if source_view == FedoView.TIME_ENERGY and target_view == FedoView.L_OMEGAD:
        return lookup.lut_te, lookup.lut_lw
    if source_view == FedoView.L_OMEGAD and target_view == FedoView.TIME_ENERGY:
        return lookup.lut_lw, lookup.lut_te
    raise ValueError(f"invalid view mapping source={source_view} target={target_view}")


def _geometry_to_vertices(geometry: dict[str, Any]) -> np.ndarray:
    quad8 = geometry_to_quad8_local(geometry)
    return np.asarray(quad8, dtype=np.float32).reshape(4, 2)


def _obb_vertices_to_geometry(vertices: np.ndarray) -> dict[str, Any]:
    points = np.asarray(vertices, dtype=np.float32).reshape(-1, 2)
    if points.shape != (4, 2):
        raise ValueError("mapped vertices must contain exactly 4 points")

    payload = quad8_to_obb_payload(points.reshape(-1).tolist(), fit_mode="strict_then_min_area")
    obb = payload.get("obb")
    if not isinstance(obb, dict):
        raise ValueError("mapped vertices cannot be fitted into obb")
    return {
        "obb": {
            "cx": float(obb.get("cx", 0.0)),
            "cy": float(obb.get("cy", 0.0)),
            "width": float(obb.get("width", 0.0)),
            "height": float(obb.get("height", 0.0)),
            "angle_deg_ccw": float(obb.get("angle_deg_ccw", 0.0)),
        }
    }


def _maybe_convert_to_rect(geometry: dict[str, Any]) -> dict[str, Any]:
    obb = geometry.get("obb")
    if not isinstance(obb, dict):
        return geometry

    angle = float(obb.get("angle_deg_ccw", obb.get("angleDegCcw", 0.0)))
    if abs(angle) > 1e-6:
        return geometry

    quad8 = geometry_to_quad8_local(geometry)
    x, y, width, height = quad8_to_aabb_rect(quad8)
    return {
        "rect": {
            "x": float(x),
            "y": float(y),
            "width": float(width),
            "height": float(height),
        }
    }
