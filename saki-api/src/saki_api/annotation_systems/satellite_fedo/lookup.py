"""
高效的 LUT 查找表生成模块，使用 NumPy 矢量化实现。
生成两个独立的像素坐标矩阵用于双视图标注系统。

核心数据结构：
- lut_te: (N, M, 2) float32 数组，存储 T-E 图的 [x_pixel, y_pixel]
- lut_lw: (N, M, 2) float32 数组，存储 L-Wd 图的 [x_pixel, y_pixel]
"""

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

import numpy as np


@dataclass
class LookupTable:
    """
    像素坐标查找表。
    
    只存储两个核心矩阵，用于从数据索引 (i, j) 直接映射到像素坐标。
    """
    n_time: int  # N - 时间点数
    n_energy: int  # M - 能量通道数
    lut_te: np.ndarray  # (N, M, 2) T-E 图像素坐标 [x, y]
    lut_lw: np.ndarray  # (N, M, 2) L-Wd 图像素坐标 [x, y]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典用于 JSON 序列化。"""
        return {
            'n_time': self.n_time,
            'n_energy': self.n_energy,
            'lut_te': self.lut_te.tolist(),
            'lut_lw': self.lut_lw.tolist(),
        }

    def to_binary(self) -> bytes:
        """
        转换为紧凑二进制格式用于高效传输。
        格式：
        - Header: n_time (4B), n_energy (4B)
        - lut_te: float32 (N * M * 2 * 4B)
        - lut_lw: float32 (N * M * 2 * 4B)
        """
        import struct

        header = struct.pack(
            '<II',  # 2 uint32
            self.n_time,
            self.n_energy,
        )

        lut_te_bytes = self.lut_te.tobytes()
        lut_lw_bytes = self.lut_lw.tobytes()

        return header + lut_te_bytes + lut_lw_bytes

    @classmethod
    def from_binary(cls, data: bytes) -> 'LookupTable':
        """从二进制数据重构查找表。"""
        import struct

        n_time, n_energy = struct.unpack('<II', data[:8])
        offset = 8

        lut_te_size = n_time * n_energy * 2 * 4  # float32 = 4 bytes
        lut_te = np.frombuffer(data[offset:offset + lut_te_size], dtype=np.float32)
        lut_te = lut_te.reshape(n_time, n_energy, 2)
        offset += lut_te_size

        lut_lw_size = n_time * n_energy * 2 * 4
        lut_lw = np.frombuffer(data[offset:offset + lut_lw_size], dtype=np.float32)
        lut_lw = lut_lw.reshape(n_time, n_energy, 2)

        return cls(
            n_time=n_time,
            n_energy=n_energy,
            lut_te=lut_te,
            lut_lw=lut_lw,
        )


def generate_pixel_lut(
    data: Dict[str, Any],
    image_width: float,
    image_height: float,
    l_xlim: Optional[Tuple[float, float]] = None,
    wd_ylim: Optional[Tuple[float, float]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    使用 NumPy 矢量化生成像素坐标查找表。
    
    此函数完全使用广播和矢量化操作，无任何 Python 循环。
    目标是在 10ms 内完成 2700 × 140 规模的计算。
    
    Args:
        data: 物理数据字典，包含：
            - L: (N,) L-shell 值
            - E: (M,) 能量中心值（keV）
            - Wd: (N, M) 漂移频率矩阵
        image_width: 图像宽度（像素）
        image_height: 图像高度（像素）
        l_xlim: L-shell 轴范围 [L_min, L_max]（用于 L-Wd 图）
        wd_ylim: 漂移频率轴范围 [Wd_min, Wd_max]（用于 L-Wd 图）
        
    Returns:
        Tuple of (lut_te, lut_lw):
            - lut_te: (N, M, 2) float32 数组，存储 [x_pixel, y_pixel] for T-E 图
            - lut_lw: (N, M, 2) float32 数组，存储 [x_pixel, y_pixel] for L-Wd 图
    """
    # 提取数据维度
    L = np.asarray(data['L'], dtype=np.float64)  # (N,)
    E = np.asarray(data['E'], dtype=np.float64)  # (M,)
    Wd = np.asarray(data['Wd'], dtype=np.float64)  # (N, M)
    
    N = L.shape[0]  # 时间采样点数
    M = E.shape[0]  # 能量通道数
    
    # 初始化输出数组 (N, M, 2)
    lut_te = np.zeros((N, M, 2), dtype=np.float32)
    lut_lw = np.zeros((N, M, 2), dtype=np.float32)
    
    # ============================================
    # T-E 图 (Plot A): 时间 vs 能量
    # ============================================
    # X 轴：时间（线性映射）
    # 时间索引 i ∈ [0, N-1] → 像素 x ∈ [0, width]
    # 使用广播：从 (N,) 扩展到 (N, M)
    time_indices = np.arange(N, dtype=np.float64)  # (N,)
    if N > 1:
        # 线性归一化：i / (N-1) → [0, 1]
        x_norm_te = time_indices[:, np.newaxis] / (N - 1)  # (N, 1) 广播到 (N, M)
    else:
        x_norm_te = np.zeros((N, 1), dtype=np.float64)
    x_pixel_te = x_norm_te * image_width  # (N, M)
    
    # Y 轴：能量（对数 log10 映射）
    # 能量 E ∈ [E_min, E_max] → log10(E) ∈ [log10(E_min), log10(E_max)] → 像素 y
    # 注意：需要翻转 Y 坐标（图像原点在左上角，物理绘图原点在左下角）
    E_valid = E[(E > 0) & np.isfinite(E)]  # 只考虑有效的正能量值
    if len(E_valid) > 0:
        E_min = np.min(E_valid)
        E_max = np.max(E_valid)
    else:
        # 如果没有有效值，使用默认范围
        E_min = 1.0
        E_max = 1000.0
    
    # 确保 E_min > 0 且有效，E_max > E_min
    if not np.isfinite(E_min) or E_min <= 0:
        E_min = 1.0
    if not np.isfinite(E_max) or E_max <= E_min:
        E_max = E_min * 10.0  # 默认范围
    
    log_E_min = np.log10(E_min)
    log_E_max = np.log10(E_max)
    log_E_range = log_E_max - log_E_min
    
    # 计算 log10(E)，处理无效值和边界
    # E 是 (M,) 数组，需要广播到 (N, M)
    E_broadcast = E[np.newaxis, :]  # (1, M) 广播到 (N, M)
    
    # 安全地计算 log10，避免 inf/NaN
    E_clipped = np.clip(E_broadcast, E_min, E_max)  # (N, M)
    log_E = np.log10(E_clipped)  # (N, M)
    
    # 替换任何 inf/NaN 为边界值
    log_E = np.where(np.isfinite(log_E), log_E, log_E_min)
    
    # 归一化到 [0, 1]：y_norm = 1 - (log_E - log_E_min) / range
    # 翻转：y=0（顶部，最大能量）→ y_norm=0, y=height（底部，最小能量）→ y_norm=1
    if log_E_range > 0:
        y_norm_te = 1.0 - (log_E - log_E_min) / log_E_range  # (N, M)
    else:
        y_norm_te = np.full((N, M), 0.5, dtype=np.float64)
    
    y_norm_te = np.clip(y_norm_te, 0.0, 1.0)
    y_pixel_te_physical = y_norm_te * image_height  # (N, M) 物理坐标（原点在左下）
    
    # Y 坐标翻转：Py_pixel = Height - Py_physical
    y_pixel_te = image_height - y_pixel_te_physical  # (N, M)
    
    # 组装 lut_te: (N, M, 2)
    lut_te[:, :, 0] = x_pixel_te.astype(np.float32)
    lut_te[:, :, 1] = y_pixel_te.astype(np.float32)
    
    # ============================================
    # L-Wd 图 (Plot B): L-shell vs 漂移频率
    # ============================================
    # X 轴：L（线性映射）
    # L ∈ [L_min, L_max] → 像素 x ∈ [0, width]
    if l_xlim is not None:
        L_min_plot, L_max_plot = l_xlim
    else:
        L_min_plot = np.nanmin(L)
        L_max_plot = np.nanmax(L)
        if not np.isfinite(L_min_plot) or not np.isfinite(L_max_plot):
            L_min_plot, L_max_plot = 1.0, 2.0  # 默认范围
    
    L_range = L_max_plot - L_min_plot
    
    # L 是 (N,) 数组，需要广播到 (N, M)
    L_broadcast = L[:, np.newaxis]  # (N, 1) 广播到 (N, M)
    L_clipped = np.clip(L_broadcast, L_min_plot, L_max_plot)
    
    # 归一化：x_norm = (L - L_min) / range
    if L_range > 0:
        x_norm_lw = (L_clipped - L_min_plot) / L_range  # (N, M)
    else:
        x_norm_lw = np.full((N, M), 0.5, dtype=np.float64)
    
    x_norm_lw = np.clip(x_norm_lw, 0.0, 1.0)
    x_pixel_lw = x_norm_lw * image_width  # (N, M)
    
    # Y 轴：Wd（线性映射）
    # Wd ∈ [Wd_min, Wd_max] → 像素 y ∈ [0, height]
    if wd_ylim is not None:
        Wd_min_plot, Wd_max_plot = wd_ylim
    else:
        Wd_min_plot = np.nanmin(Wd)
        Wd_max_plot = np.nanmax(Wd)
        if not np.isfinite(Wd_min_plot) or not np.isfinite(Wd_max_plot):
            Wd_min_plot, Wd_max_plot = 0.0, 4.0  # 默认范围
    
    Wd_range = Wd_max_plot - Wd_min_plot
    
    # Wd 已经是 (N, M) 矩阵
    Wd_clipped = np.clip(Wd, Wd_min_plot, Wd_max_plot)
    
    # 替换任何 inf/NaN
    Wd_clipped = np.where(np.isfinite(Wd_clipped), Wd_clipped, Wd_min_plot)
    
    # 归一化：y_norm = 1 - (Wd - Wd_min) / range（翻转）
    if Wd_range > 0:
        y_norm_lw = 1.0 - (Wd_clipped - Wd_min_plot) / Wd_range  # (N, M)
    else:
        y_norm_lw = np.full((N, M), 0.5, dtype=np.float64)
    
    y_norm_lw = np.clip(y_norm_lw, 0.0, 1.0)
    y_pixel_lw_physical = y_norm_lw * image_height  # (N, M) 物理坐标
    
    # Y 坐标翻转：Py_pixel = Height - Py_physical
    y_pixel_lw = image_height - y_pixel_lw_physical  # (N, M)
    
    # 组装 lut_lw: (N, M, 2)
    lut_lw[:, :, 0] = x_pixel_lw.astype(np.float32)
    lut_lw[:, :, 1] = y_pixel_lw.astype(np.float32)
    
    return lut_te, lut_lw


def generate_lookup_table(
    data: Dict[str, Any],
    output_path: Optional[str] = None,
    image_width: Optional[float] = None,
    image_height: Optional[float] = None,
    l_xlim: Optional[Tuple[float, float]] = None,
    wd_ylim: Optional[Tuple[float, float]] = None,
) -> LookupTable:
    """
    生成像素坐标查找表。
    
    Args:
        data: 来自 calculate_physics_data 的物理数据字典
        output_path: 保存为文件的路径（可选，使用 .npz 格式）
        image_width: 图像宽度（像素）。如果未提供，将根据默认配置计算
        image_height: 图像高度（像素）。如果未提供，将根据默认配置计算
        l_xlim: L-shell 轴范围 [L_min, L_max]（可选）
        wd_ylim: 漂移频率轴范围 [Wd_min, Wd_max]（可选）
        
    Returns:
        LookupTable 对象，只包含两个 LUT 矩阵
    """
    N = len(data['L'])
    M = len(data['E'])
    
    # 计算图像尺寸（如果未提供）
    if image_width is None or image_height is None:
        # 默认配置：figsize=(6, 4) 英寸, dpi=200
        default_figsize = (6.0, 4.0)
        default_dpi = 200
        if image_width is None:
            image_width = default_figsize[0] * default_dpi
        if image_height is None:
            image_height = default_figsize[1] * default_dpi
    
    # 生成像素坐标查找表（矢量化实现）
    lut_te, lut_lw = generate_pixel_lut(
        data,
        image_width=image_width,
        image_height=image_height,
        l_xlim=l_xlim,
        wd_ylim=wd_ylim,
    )

    lookup = LookupTable(
        n_time=N,
        n_energy=M,
        lut_te=lut_te,
        lut_lw=lut_lw,
    )

    if output_path:
        save_lookup_table(lookup, output_path)

    return lookup


def save_lookup_table(lookup: LookupTable, output_path: str) -> None:
    """
    保存查找表到文件。
    
    使用 .npz 格式（NumPy 压缩数组格式）以高效存储两个矩阵。
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    # 确保使用 .npz 格式
    if not output_path.endswith('.npz'):
        output_path = output_path + '.npz'
    
    np.savez_compressed(
        output_path,
        n_time=lookup.n_time,
        n_energy=lookup.n_energy,
        lut_te=lookup.lut_te,
        lut_lw=lookup.lut_lw,
    )


def load_lookup_table(file_path: str) -> LookupTable:
    """
    从文件加载查找表。
    
    只支持 .npz 格式。
    """
    if not file_path.endswith('.npz'):
        raise ValueError(f"查找表文件必须是 .npz 格式: {file_path}")
    
    data = np.load(file_path)
    return LookupTable(
        n_time=int(data['n_time']),
        n_energy=int(data['n_energy']),
        lut_te=data['lut_te'],
        lut_lw=data['lut_lw'],
    )


def get_pixel_coordinates(
    lookup: LookupTable,
    indices: np.ndarray,
    view: str = 'te'
) -> np.ndarray:
    """
    从数据索引获取像素坐标。
    
    Args:
        lookup: LookupTable 对象
        indices: (K, 2) 数组，存储 (time_idx, energy_idx) 对
        view: 视图类型，'te' 或 'lw'
        
    Returns:
        (K, 2) 数组，存储 [x_pixel, y_pixel]
    """
    i = np.clip(indices[:, 0].astype(int), 0, lookup.n_time - 1)
    j = np.clip(indices[:, 1].astype(int), 0, lookup.n_energy - 1)
    
    if view == 'te':
        return lookup.lut_te[i, j, :]  # (K, 2)
    elif view == 'lw':
        return lookup.lut_lw[i, j, :]  # (K, 2)
    else:
        raise ValueError(f"未知视图类型: {view}。必须是 'te' 或 'lw'")
