"""
高性能 OBB 标注映射模块。

实现从源视图的 OBB 标注自动推导出目标视图对应标注的逻辑。
使用完全矢量化操作，满足处理 37 万个点在 50-100ms 内的性能要求。

核心算法：
1. 双级掩码筛选（AABB 粗筛 + Point-in-Polygon 精筛）
2. 时间轴跳变分段
3. 目标 OBB 拟合（cv2.minAreaRect）
"""

from typing import List

import cv2
import numpy as np
from matplotlib.path import Path


def map_obb_annotations(
    src_obb_vertices: np.ndarray,
    lut_src: np.ndarray,
    lut_dst: np.ndarray,
    time_gap_threshold: int = 50,
) -> List[np.ndarray]:
    """
    从源视图的 OBB 标注推导出目标视图对应的 OBB 标注。

    此函数实现极速处理流程，使用完全矢量化操作，无任何 Python 原生循环。
    目标性能：处理 37 万个点在 50-100ms 内完成。

    Args:
        src_obb_vertices: 源图中 OBB 的四个顶点像素坐标，形状为 (4, 2)
        lut_src: 源图的像素映射表矩阵，形状为 (N, M, 2)
                 lut_src[i, j] = [x_pixel, y_pixel] 表示数据索引 (i, j) 在源图中的像素坐标
        lut_dst: 目标图的像素映射表矩阵，形状为 (N, M, 2)
                 lut_dst[i, j] = [x_pixel, y_pixel] 表示数据索引 (i, j) 在目标图中的像素坐标
        time_gap_threshold: 时间轴跳变阈值，用于判断点云是否在时间上断开（默认 50）

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
    # 输入验证
    if src_obb_vertices.shape != (4, 2):
        raise ValueError(f"src_obb_vertices 形状必须为 (4, 2)，实际为 {src_obb_vertices.shape}")
    
    if len(lut_src.shape) != 3 or lut_src.shape[2] != 2:
        raise ValueError(f"lut_src 形状必须为 (N, M, 2)，实际为 {lut_src.shape}")
    
    if lut_src.shape != lut_dst.shape:
        raise ValueError(f"lut_src 和 lut_dst 形状必须相同，实际为 {lut_src.shape} vs {lut_dst.shape}")
    
    N, M = lut_src.shape[:2]
    
    # ============================================
    # 步骤 1: 双级掩码筛选
    # ============================================
    
    # 步骤 1.1: 粗筛 - 计算 AABB（轴对齐边界框）
    min_x = np.min(src_obb_vertices[:, 0])
    max_x = np.max(src_obb_vertices[:, 0])
    min_y = np.min(src_obb_vertices[:, 1])
    max_y = np.max(src_obb_vertices[:, 1])
    
    # 提取源图 LUT 的像素坐标
    src_pixels = lut_src.reshape(-1, 2)  # (N*M, 2)
    
    # 使用布尔掩码快速筛选可能在 AABB 内的点
    in_aabb_mask = (
        (src_pixels[:, 0] >= min_x) & (src_pixels[:, 0] <= max_x) &
        (src_pixels[:, 1] >= min_y) & (src_pixels[:, 1] <= max_y)
    )
    
    # 获取粗筛后的点索引（一维索引）
    candidate_1d_indices = np.where(in_aabb_mask)[0]
    
    if len(candidate_1d_indices) == 0:
        return []
    
    # 转换回二维索引 (rows, cols)
    candidate_rows = candidate_1d_indices // M  # (K,)
    candidate_cols = candidate_1d_indices % M   # (K,)
    
    # 步骤 1.2: 精筛 - Point-in-Polygon 判断
    # 提取候选点的像素坐标
    candidate_pixels = src_pixels[candidate_1d_indices]  # (K, 2)
    
    # 使用 matplotlib.path.Path.contains_points 进行矢量化点内判断
    polygon_path = Path(src_obb_vertices)
    in_polygon_mask = polygon_path.contains_points(candidate_pixels)  # (K,)
    
    # 更新 rows 和 cols，只保留真正在 OBB 内的点
    rows = candidate_rows[in_polygon_mask]  # (K',)
    cols = candidate_cols[in_polygon_mask]  # (K',)
    
    if len(rows) == 0:
        return []
    
    # ============================================
    # 步骤 2: 时间轴跳变分段
    # ============================================
    
    # 对行索引进行去重并排序
    unique_rows = np.unique(rows)
    
    if len(unique_rows) <= 1:
        # 只有一个或零个唯一行，不需要分段
        clusters = [(rows, cols)]
    else:
        # 计算相邻行索引的差值
        row_diffs = np.diff(unique_rows)  # (L-1,)
        
        # 找出跳变点（差值大于阈值的位置）
        jump_indices = np.where(row_diffs > time_gap_threshold)[0]  # 跳变点的位置（在 unique_rows 中的索引）
        
        if len(jump_indices) == 0:
            # 没有跳变，所有点属于一个组
            clusters = [(rows, cols)]
        else:
            # 根据跳变点将点云分段
            # 将 rows 和 cols 按行索引排序，便于分段
            sort_indices = np.argsort(rows)
            sorted_rows = rows[sort_indices]
            sorted_cols = cols[sort_indices]
            
            # 计算每个跳变点在 sorted_rows 中的分割位置
            # jump_indices[i] 表示在 unique_rows[jump_indices[i]] 和 unique_rows[jump_indices[i]+1] 之间有跳变
            # 分割点：跳变后的第一个行值在 sorted_rows 中的位置
            split_rows_after_jump = unique_rows[jump_indices + 1]  # 跳变后的第一个行值
            split_positions = np.searchsorted(sorted_rows, split_rows_after_jump, side='left')
            
            # 添加起始和结束位置，使用 np.split 进行分割
            split_positions = np.concatenate([[0], split_positions, [len(sorted_rows)]])
            
            # 使用 np.split 分割数组
            clusters = []
            for i in range(len(split_positions) - 1):
                start_idx = split_positions[i]
                end_idx = split_positions[i + 1]
                if end_idx > start_idx:
                    clusters.append((
                        sorted_rows[start_idx:end_idx],
                        sorted_cols[start_idx:end_idx]
                    ))
    
    # ============================================
    # 步骤 3: 目标 OBB 拟合
    # ============================================
    
    result_obbs = []
    min_points_threshold = 5  # 最少点数阈值
    
    for cluster_rows, cluster_cols in clusters:
        # 检查点数
        if len(cluster_rows) < min_points_threshold:
            continue
        
        # 从 lut_dst 中查找目标图对应的像素坐标
        # 注意：cluster_rows 和 cluster_cols 可能包含重复的 (row, col) 对
        # 但我们需要保持一一对应关系
        target_pixels = lut_dst[cluster_rows, cluster_cols]  # (K, 2)
        
        # 使用 cv2.minAreaRect 拟合最小面积矩形
        # cv2.minAreaRect 需要输入 shape 为 (N, 1, 2) 的数组
        points_for_cv = target_pixels.reshape(-1, 1, 2).astype(np.float32)
        
        # 调用 cv2.minAreaRect
        rect = cv2.minAreaRect(points_for_cv)
        
        # 获取旋转矩形的四个顶点
        box_points = cv2.boxPoints(rect)  # (4, 2)
        
        # 添加到结果列表
        result_obbs.append(box_points)
    
    return result_obbs

