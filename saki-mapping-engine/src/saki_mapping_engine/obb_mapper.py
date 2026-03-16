from __future__ import annotations

from typing import Optional

import cv2
from matplotlib.path import Path
import numpy as np


def _validate_mapper_inputs(
    *,
    src_obb_vertices: np.ndarray,
    lut_src: np.ndarray,
    lut_dst: np.ndarray,
) -> None:
    if src_obb_vertices.shape != (4, 2):
        raise ValueError(f"src_obb_vertices 形状必须为 (4, 2)，实际为 {src_obb_vertices.shape}")
    if len(lut_src.shape) != 3 or lut_src.shape[2] != 2:
        raise ValueError(f"lut_src 形状必须为 (N, M, 2)，实际为 {lut_src.shape}")
    if lut_src.shape != lut_dst.shape:
        raise ValueError(f"lut_src 和 lut_dst 形状必须相同，实际为 {lut_src.shape} vs {lut_dst.shape}")


def _aabb_candidate_indices(
    *,
    src_obb_vertices: np.ndarray,
    lut_src: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    min_x = np.min(src_obb_vertices[:, 0])
    max_x = np.max(src_obb_vertices[:, 0])
    min_y = np.min(src_obb_vertices[:, 1])
    max_y = np.max(src_obb_vertices[:, 1])

    src_pixels = lut_src.reshape(-1, 2)
    in_aabb_mask = (
        (src_pixels[:, 0] >= min_x)
        & (src_pixels[:, 0] <= max_x)
        & (src_pixels[:, 1] >= min_y)
        & (src_pixels[:, 1] <= max_y)
    )
    candidate_1d_indices = np.where(in_aabb_mask)[0]
    return src_pixels, candidate_1d_indices, int(lut_src.shape[1])


def _polygon_filter_candidates(
    *,
    src_obb_vertices: np.ndarray,
    src_pixels: np.ndarray,
    candidate_1d_indices: np.ndarray,
    width: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    candidate_rows = candidate_1d_indices // width
    candidate_cols = candidate_1d_indices % width
    candidate_pixels = src_pixels[candidate_1d_indices]

    polygon_path = Path(src_obb_vertices)
    in_polygon_mask = polygon_path.contains_points(candidate_pixels)

    rows = candidate_rows[in_polygon_mask]
    cols = candidate_cols[in_polygon_mask]
    src_selected_pixels = candidate_pixels[in_polygon_mask]
    return rows, cols, src_selected_pixels


def _split_clusters_by_time_gap(
    *,
    rows: np.ndarray,
    cols: np.ndarray,
    time_gap_threshold: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    unique_rows = np.unique(rows)
    if len(unique_rows) <= 1:
        return [(rows, cols)]

    row_diffs = np.diff(unique_rows)
    jump_indices = np.where(row_diffs > time_gap_threshold)[0]
    if len(jump_indices) == 0:
        return [(rows, cols)]

    sort_indices = np.argsort(rows)
    sorted_rows = rows[sort_indices]
    sorted_cols = cols[sort_indices]

    split_rows_after_jump = unique_rows[jump_indices + 1]
    split_positions = np.searchsorted(sorted_rows, split_rows_after_jump, side="left")
    split_positions = np.concatenate([[0], split_positions, [len(sorted_rows)]])

    clusters: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(len(split_positions) - 1):
        start_idx = split_positions[i]
        end_idx = split_positions[i + 1]
        if end_idx <= start_idx:
            continue
        clusters.append((sorted_rows[start_idx:end_idx], sorted_cols[start_idx:end_idx]))
    return clusters


def _fit_target_obbs(
    *,
    lut_dst: np.ndarray,
    clusters: list[tuple[np.ndarray, np.ndarray]],
    min_points_threshold: int = 5,
) -> list[np.ndarray]:
    result_obbs: list[np.ndarray] = []

    for cluster_rows, cluster_cols in clusters:
        if len(cluster_rows) < min_points_threshold:
            continue
        target_pixels = lut_dst[cluster_rows, cluster_cols]
        points_for_cv = target_pixels.reshape(-1, 1, 2).astype(np.float32)
        rect = cv2.minAreaRect(points_for_cv)
        box_points = cv2.boxPoints(rect)
        result_obbs.append(box_points)
    return result_obbs


def map_obb_annotations(
    src_obb_vertices: np.ndarray,
    lut_src: np.ndarray,
    lut_dst: np.ndarray,
    time_gap_threshold: int = 50,
    debug_output_dir: Optional[str] = None,
) -> list[np.ndarray]:
    del debug_output_dir

    _validate_mapper_inputs(src_obb_vertices=src_obb_vertices, lut_src=lut_src, lut_dst=lut_dst)
    src_pixels, candidate_1d_indices, width = _aabb_candidate_indices(
        src_obb_vertices=src_obb_vertices,
        lut_src=lut_src,
    )
    if len(candidate_1d_indices) == 0:
        return []

    rows, cols, _ = _polygon_filter_candidates(
        src_obb_vertices=src_obb_vertices,
        src_pixels=src_pixels,
        candidate_1d_indices=candidate_1d_indices,
        width=width,
    )
    if len(rows) == 0:
        return []

    clusters = _split_clusters_by_time_gap(
        rows=rows,
        cols=cols,
        time_gap_threshold=time_gap_threshold,
    )
    return _fit_target_obbs(lut_dst=lut_dst, clusters=clusters)
