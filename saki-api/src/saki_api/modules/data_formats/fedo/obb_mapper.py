"""
高性能 OBB 标注映射模块。

实现从源视图的 OBB 标注自动推导出目标视图对应标注的逻辑。
使用完全矢量化操作，满足处理 37 万个点在 50-100ms 内的性能要求。

核心算法：
1. 双级掩码筛选（AABB 粗筛 + Point-in-Polygon 精筛）
2. 时间轴跳变分段
3. 目标 OBB 拟合（cv2.minAreaRect）
"""

import os
from typing import List, Optional

import cv2
import numpy as np
from matplotlib.path import Path


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
            (src_pixels[:, 0] >= min_x) & (src_pixels[:, 0] <= max_x) &
            (src_pixels[:, 1] >= min_y) & (src_pixels[:, 1] <= max_y)
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
    split_positions = np.searchsorted(sorted_rows, split_rows_after_jump, side='left')
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
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    result_obbs: list[np.ndarray] = []
    all_target_pixels_list: list[np.ndarray] = []

    for cluster_rows, cluster_cols in clusters:
        if len(cluster_rows) < min_points_threshold:
            continue
        target_pixels = lut_dst[cluster_rows, cluster_cols]
        all_target_pixels_list.append(target_pixels)

        points_for_cv = target_pixels.reshape(-1, 1, 2).astype(np.float32)
        rect = cv2.minAreaRect(points_for_cv)
        box_points = cv2.boxPoints(rect)
        result_obbs.append(box_points)
    return result_obbs, all_target_pixels_list


def _generate_mapper_debug_images(
        *,
        debug_output_dir: Optional[str],
        src_selected_pixels: np.ndarray,
        all_target_pixels_list: list[np.ndarray],
        lut_src: np.ndarray,
        lut_dst: np.ndarray,
) -> None:
    if debug_output_dir is None:
        return
    _generate_debug_images(
        src_selected_pixels=src_selected_pixels,
        all_target_pixels_list=all_target_pixels_list,
        lut_src=lut_src,
        lut_dst=lut_dst,
        output_dir=debug_output_dir,
    )


def map_obb_annotations(
        src_obb_vertices: np.ndarray,
        lut_src: np.ndarray,
        lut_dst: np.ndarray,
        time_gap_threshold: int = 50,
        debug_output_dir: Optional[str] = None,
) -> List[np.ndarray]:
    """
    从源视图的 OBB 标注推导出目标视图对应的 OBB 标注。

    Args:
        src_obb_vertices: 源图中 OBB 的四个顶点像素坐标，形状为 (4, 2)
        lut_src: 源图的像素映射表矩阵，形状为 (N, M, 2)
                 lut_src[i, j] = [x_pixel, y_pixel] 表示数据索引 (i, j) 在源图中的像素坐标
        lut_dst: 目标图的像素映射表矩阵，形状为 (N, M, 2)
                 lut_dst[i, j] = [x_pixel, y_pixel] 表示数据索引 (i, j) 在目标图中的像素坐标
        time_gap_threshold: 时间轴跳变阈值，用于判断点云是否在时间上断开（默认 50）
        debug_output_dir: 可选的调试输出目录。如果提供，将生成两张调试图片：
                          - src_debug.png: 显示源图中筛选出的点集（高亮显示）
                          - dst_debug.png: 显示目标图中对应的点集（高亮显示）

    Returns:
        目标 OBB 顶点列表，每个元素是一个 (4, 2) 的数组，表示一个目标 OBB 的四个顶点坐标。
        如果某个点云组的点数少于 5 个，会被忽略，不生成 OBB。
        如果没有任何有效点，返回空列表。

    算法流程：
        1. 双级掩码筛选：
           - 粗筛：计算 src_obb_vertices 的最小轴向外接矩形（AABB），快速提取可能在框内的点
           - 精筛：使用 Point-in-Polygon 判断点是否真正落在 OBB 四边形内
        2. 时间轴跳变分段：
           - 对筛选出的行索引 rows 进行去重并排序
           - 计算相邻行索引的差值，如果存在差值大于 time_gap_threshold 的位置，
             将点云拆分为多个独立的组（Clusters）
        3. 目标 OBB 拟合：
           - 对于每一个点云组，从 lut_dst 中查找其在目标图对应的像素坐标集
           - 调用 cv2.minAreaRect 对点云集进行拟合，生成目标图中的 OBB
           - 如果某组点数过少（少于 5 个点），予以忽略

    性能约束：
        - 严禁在点处理级别使用 Python 原生循环
        - 所有操作必须使用 NumPy 矢量化或 OpenCV 函数
        - 目标处理时间：50-100ms for 37 万个点
    """
    _validate_mapper_inputs(src_obb_vertices=src_obb_vertices, lut_src=lut_src, lut_dst=lut_dst)
    src_pixels, candidate_1d_indices, width = _aabb_candidate_indices(
        src_obb_vertices=src_obb_vertices,
        lut_src=lut_src,
    )
    if len(candidate_1d_indices) == 0:
        _generate_mapper_debug_images(
            debug_output_dir=debug_output_dir,
            src_selected_pixels=np.array([], dtype=np.float32).reshape(0, 2),
            all_target_pixels_list=[],
            lut_src=lut_src,
            lut_dst=lut_dst,
        )
        return []

    rows, cols, src_selected_pixels = _polygon_filter_candidates(
        src_obb_vertices=src_obb_vertices,
        src_pixels=src_pixels,
        candidate_1d_indices=candidate_1d_indices,
        width=width,
    )
    if len(rows) == 0:
        _generate_mapper_debug_images(
            debug_output_dir=debug_output_dir,
            src_selected_pixels=np.array([], dtype=np.float32).reshape(0, 2),
            all_target_pixels_list=[],
            lut_src=lut_src,
            lut_dst=lut_dst,
        )
        return []

    clusters = _split_clusters_by_time_gap(
        rows=rows,
        cols=cols,
        time_gap_threshold=time_gap_threshold,
    )
    result_obbs, all_target_pixels_list = _fit_target_obbs(lut_dst=lut_dst, clusters=clusters)
    _generate_mapper_debug_images(
        debug_output_dir=debug_output_dir,
        src_selected_pixels=src_selected_pixels,
        all_target_pixels_list=all_target_pixels_list,
        lut_src=lut_src,
        lut_dst=lut_dst,
    )

    return result_obbs


def _generate_debug_images(
        src_selected_pixels: np.ndarray,
        all_target_pixels_list: List[np.ndarray],
        lut_src: np.ndarray,
        lut_dst: np.ndarray,
        output_dir: str,
) -> None:
    """
    生成调试图片，显示源图和目标图中的高亮点集。
    
    Args:
        src_selected_pixels: 源图中筛选出的点集，形状为 (K, 2)
        all_target_pixels_list: 目标图中所有点云组的列表，每个元素形状为 (K_i, 2)
        lut_src: 源图的像素映射表矩阵，形状为 (N, M, 2)
        lut_dst: 目标图的像素映射表矩阵，形状为 (N, M, 2)
        output_dir: 输出目录路径
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 计算图像尺寸（从 LUT 中获取最大像素坐标，并添加一些边距）
    src_pixels_flat = lut_src.reshape(-1, 2)
    dst_pixels_flat = lut_dst.reshape(-1, 2)

    # 获取有效像素坐标（排除 NaN 或无效值）
    src_valid = src_pixels_flat[np.isfinite(src_pixels_flat).all(axis=1)]
    dst_valid = dst_pixels_flat[np.isfinite(dst_pixels_flat).all(axis=1)]

    if len(src_valid) == 0 or len(dst_valid) == 0:
        return  # 如果没有有效点，跳过图片生成

    # 计算图像尺寸（添加 50 像素边距）
    margin = 50
    src_width = int(np.max(src_valid[:, 0]) + margin)
    src_height = int(np.max(src_valid[:, 1]) + margin)
    dst_width = int(np.max(dst_valid[:, 0]) + margin)
    dst_height = int(np.max(dst_valid[:, 1]) + margin)

    # 创建源图调试图片（黑色背景）
    src_debug_img = np.zeros((src_height, src_width), dtype=np.uint8)

    # 将筛选出的点设置为白色（255）
    if len(src_selected_pixels) > 0:
        valid_src_mask = np.isfinite(src_selected_pixels).all(axis=1)
        valid_src_pixels = src_selected_pixels[valid_src_mask]

        # 将坐标转换为整数索引，并确保在图像范围内
        src_x = np.clip(valid_src_pixels[:, 0].astype(int), 0, src_width - 1)
        src_y = np.clip(valid_src_pixels[:, 1].astype(int), 0, src_height - 1)

        # 设置点集位置为白色
        src_debug_img[src_y, src_x] = 255

    # 保存源图调试图片
    src_debug_path = os.path.join(output_dir, "src_debug.png")
    cv2.imwrite(src_debug_path, src_debug_img)

    # 创建目标图调试图片（黑色背景）
    dst_debug_img = np.zeros((dst_height, dst_width), dtype=np.uint8)

    # 将所有目标点云组的点设置为白色
    for target_pixels in all_target_pixels_list:
        if len(target_pixels) > 0:
            valid_dst_mask = np.isfinite(target_pixels).all(axis=1)
            valid_dst_pixels = target_pixels[valid_dst_mask]

            # 将坐标转换为整数索引，并确保在图像范围内
            dst_x = np.clip(valid_dst_pixels[:, 0].astype(int), 0, dst_width - 1)
            dst_y = np.clip(valid_dst_pixels[:, 1].astype(int), 0, dst_height - 1)

            # 设置点集位置为白色
            dst_debug_img[dst_y, dst_x] = 255

    # 保存目标图调试图片
    dst_debug_path = os.path.join(output_dir, "dst_debug.png")
    cv2.imwrite(dst_debug_path, dst_debug_img)
