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
    
    存储两个核心矩阵，用于从数据索引 (i, j) 直接映射到像素坐标。
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
        转换为紧凑二进制格式。
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
    """
    # 提取并转换基础数据
    L = np.asarray(data['L'], dtype=np.float64)  # (N,)
    E = np.asarray(data['E'], dtype=np.float64)  # (M,)
    Wd = np.asarray(data['Wd'], dtype=np.float64)  # (N, M)

    # 关键修复：将时间戳转换为数值，用于精确线性映射
    time_val = np.asarray(data['time'], dtype='datetime64[ns]').view('int64').astype(np.float64)  # (N,)

    N, M = Wd.shape

    lut_te = np.zeros((N, M, 2), dtype=np.float32)
    lut_lw = np.zeros((N, M, 2), dtype=np.float32)

    # ============================================
    # T-E 视图 (Plot A): Time(X) vs Energy(Y, Log)
    # ============================================
    # X轴映射：时间数值
    t_min, t_max = time_val.min(), time_val.max()
    t_range = t_max - t_min
    x_norm_te = (time_val - t_min) / t_range if t_range > 0 else np.zeros_like(time_val)
    x_pixel_te = x_norm_te[:, np.newaxis] * image_width  # (N, 1) 广播到 (N, M)

    # Y轴映射：对数能量
    # 图像 y=0 是顶部。Spectrogram 习惯将高能 E_max 置于顶部。
    E_min, E_max = E.min(), E.max()
    log_E = np.log10(np.clip(E, E_min, E_max))
    log_E_min, log_E_max = log_E.min(), log_E.max()
    log_E_range = log_E_max - log_E_min

    # 公式：y_norm = (log_E_max - log_E) / log_E_range
    # 当 E = E_max 时，y_norm = 0 (图片顶部)
    if log_E_range > 0:
        y_norm_te = (log_E_max - log_E) / log_E_range
    else:
        y_norm_te = np.full_like(log_E, 0.5)
    y_pixel_te = y_norm_te[np.newaxis, :] * image_height  # (1, M) 广播到 (N, M)

    lut_te[:, :, 0] = np.clip(x_pixel_te, 0, image_width).astype(np.float32)
    lut_te[:, :, 1] = np.clip(y_pixel_te, 0, image_height).astype(np.float32)

    # ============================================
    # L-Wd 视图 (Plot B): L-shell(X) vs Wd(Y)
    # ============================================
    # X轴映射：L-shell
    l_min, l_max = l_xlim if l_xlim else (L.min(), L.max())
    l_range = l_max - l_min
    x_norm_lw = (L - l_min) / l_range if l_range > 0 else np.zeros_like(L)
    x_pixel_lw = x_norm_lw[:, np.newaxis] * image_width

    # Y轴映射：漂移频率 Wd
    # 图像 y=0 是顶部。通常 Wd_max 置于顶部。
    wd_min, wd_max = wd_ylim if wd_ylim else (Wd.min(), Wd.max())
    wd_range = wd_max - wd_min

    # 公式：y_norm = (wd_max - Wd) / wd_range
    if wd_range > 0:
        y_norm_lw = (wd_max - Wd) / wd_range  # (N, M)
    else:
        y_norm_lw = np.full_like(Wd, 0.5)
    y_pixel_lw = y_norm_lw * image_height

    lut_lw[:, :, 0] = np.clip(x_pixel_lw, 0, image_width).astype(np.float32)
    lut_lw[:, :, 1] = np.clip(y_pixel_lw, 0, image_height).astype(np.float32)

    return lut_te, lut_lw


def generate_lookup_table(
        data: Dict[str, Any],
        output_path: Optional[str] = None,
        image_width: Optional[float] = None,
        image_height: Optional[float] = None,
        l_xlim: Optional[Tuple[float, float]] = None,
        wd_ylim: Optional[Tuple[float, float]] = None,
) -> LookupTable:
    """生成 LookupTable 对象并可选保存到磁盘。"""
    # 统一使用默认或指定的图像尺寸
    if image_width is None or image_height is None:
        default_figsize = (6.0, 4.0)
        default_dpi = 200
        image_width = image_width or (default_figsize[0] * default_dpi)
        image_height = image_height or (default_figsize[1] * default_dpi)

    lut_te, lut_lw = generate_pixel_lut(
        data, image_width, image_height, l_xlim, wd_ylim
    )

    lookup = LookupTable(
        n_time=lut_te.shape[0],
        n_energy=lut_te.shape[1],
        lut_te=lut_te,
        lut_lw=lut_lw,
    )

    if output_path:
        save_lookup_table(lookup, output_path)

    return lookup


def save_lookup_table(lookup: LookupTable, output_path: str) -> None:
    """以压缩 .npz 格式保存查找表。"""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    if not output_path.endswith('.npz'):
        output_path += '.npz'

    np.savez_compressed(
        output_path,
        n_time=lookup.n_time,
        n_energy=lookup.n_energy,
        lut_te=lookup.lut_te,
        lut_lw=lookup.lut_lw,
    )


def load_lookup_table(file_path: str) -> LookupTable:
    """加载 .npz 查找表。"""
    data = np.load(file_path)
    return LookupTable(
        n_time=int(data['n_time']),
        n_energy=int(data['n_energy']),
        lut_te=data['lut_te'],
        lut_lw=data['lut_lw'],
    )
