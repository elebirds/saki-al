"""
Visualization module for FEDO data.
Generates pure images for Time-Energy and L-ωd views.
"""

import os

import matplotlib
import numpy as np
from matplotlib.figure import Figure

from saki_api.modules.annotation.satellite_fedo.enum import FedoView

matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from typing import Dict, Any, Tuple


def centers_to_edges_2d(Xc: np.ndarray) -> np.ndarray:
    """
    Convert cell centers to cell corners for pcolormesh.
    
    Args:
        Xc: (M, N) array of cell centers
        
    Returns:
        (M+1, N+1) array of cell corners
    """
    if Xc.ndim != 2:
        raise ValueError("centers_to_edges_2d requires 2D array")

    # Column direction: (M, N) -> (M, N+1)
    mid = 0.5 * (Xc[:, :-1] + Xc[:, 1:])
    left = Xc[:, [0]] - (mid[:, [0]] - Xc[:, [0]])
    right = Xc[:, [-1]] + (Xc[:, [-1]] - mid[:, [-1]])
    Xe_col = np.hstack([left, mid, right])

    # Row direction: (M, N+1) -> (M+1, N+1)
    mid2 = 0.5 * (Xe_col[:-1, :] + Xe_col[1:, :])
    top = Xe_col[[0], :] - (mid2[[0], :] - Xe_col[[0], :])
    bottom = Xe_col[[-1], :] + (Xe_col[[-1], :] - mid2[[-1], :])
    Xe = np.vstack([top, mid2, bottom])

    return Xe


def _get_color_norm(flux: np.ndarray) -> colors.LogNorm:
    """Get logarithmic color normalization based on flux data."""
    flux_valid = flux[np.isfinite(flux) & (flux > 0)]
    if flux_valid.size < 10:
        raise ValueError("有效 Flux 太少，无法设定 LogNorm 范围")
    vmin = np.nanpercentile(flux_valid, 5)
    vmax = np.nanpercentile(flux_valid, 99)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin <= 0 or vmax <= 0:
        raise ValueError("LogNorm vmin/vmax 非法")
    return colors.LogNorm(vmin=vmin, vmax=vmax)


def generate_pure_image(
        data: Dict[str, Any],
        view: FedoView,
        dpi,
        figsize: Tuple[float, float],
        cmap: str,
        l_xlim: Tuple[float, float],
        wd_ylim: Tuple[float, float],
) -> Figure:
    """
    Generate a pure image (no axes, labels, or colorbar) for annotation overlay.
    
    Args:
        data: Physics data dictionary from calculate_physics_data
        view: FedoView enum specifying the view type
        dpi: Image resolution
        figsize: Figure size in inches
        cmap: Colormap name
        l_xlim: L-shell axis limits (for l_wd view)
        wd_ylim: Drift frequency axis limits (for l_wd view)
        
    Returns:
        Path to the generated image
    """
    Time = data['time']
    L = data['L']
    E = data['E']
    Flux = data['Flux']
    Wd = data['Wd']

    norm = _get_color_norm(Flux)

    fig = plt.figure(figsize=figsize, dpi=dpi)  # 强制 Axes 占用 100% 的画布空间，不留边距
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))

    # P.S. / TODO: 这里这样修改好像没啥意义
    if view == FedoView.TIME_ENERGY:
        # 关键修改 2：将时间转换为数值以避免 add 报错
        time_numeric = Time.astype('datetime64[ns]').view('int64').astype(np.float64)

        # 构造 2D 网格并计算精确边缘
        T_grid, E_grid = np.meshgrid(time_numeric, E)
        T_edge = centers_to_edges_2d(T_grid)
        E_edge = centers_to_edges_2d(E_grid)

        # 使用 flat 模式配合 edges，实现像素级对齐
        ax.pcolormesh(T_edge, E_edge, Flux.T, norm=norm, cmap=cmap, shading='flat')
        ax.set_yscale('log')
    elif view == FedoView.L_WD:
        # L vs ωd view with curvilinear grid
        L_grid = np.tile(L, (len(E), 1))  # (M, N)
        Wd_grid = Wd.T  # (M, N)
        Z_data = Flux.T  # (M, N)

        L_edge = centers_to_edges_2d(L_grid)
        Wd_edge = centers_to_edges_2d(Wd_grid)

        ax.pcolormesh(
            L_edge, Wd_edge, Z_data,
            norm=norm, cmap=cmap,
            shading='flat',
            edgecolors='none',
            linewidth=0,
            rasterized=True
        )

        ax.set_xlim(*l_xlim)
        ax.set_ylim(*wd_ylim)
    else:
        raise ValueError(f"Unknown view type: {view}")

    # Remove all decorations for pure image
    ax.set_axis_off()
    # plt.tight_layout(pad=0.0)

    return fig


def save_fig_to_file(fig: Figure, file_path: str) -> None:
    """
    Save a Matplotlib figure to a PNG file.
    
    Args:
        fig: Matplotlib Figure object
        file_path: Output file path
    """
    fig.savefig(file_path, facecolor='white', pad_inches=0.0, transparent=False)
    plt.close(fig)


def save_fig_to_bytes(fig: Figure) -> bytes:
    """
    Save a Matplotlib figure to PNG bytes.
    
    Args:
        fig: Matplotlib Figure object
        
    Returns:
        PNG image bytes
    """
    import io
    buf = io.BytesIO()
    fig.savefig(buf, facecolor='white', pad_inches=0.0, transparent=False)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def generate_views(
        data: Dict[str, Any],
        output_dir: str,
        base_name: str,
        **kwargs
) -> Tuple[str, str]:
    """
    Generate both Time-Energy and L-ωd views.
    
    Args:
        data: Physics data dictionary
        output_dir: Directory to save images
        base_name: Base filename for images
        dpi: Image resolution
        **kwargs: Additional arguments for generate_pure_image
        
    Returns:
        Tuple of (time_energy_path, l_wd_path)
    """
    te_path = os.path.join(output_dir, f"{base_name}_time_energy.png")
    lwd_path = os.path.join(output_dir, f"{base_name}_l_wd.png")

    save_fig_to_file(
        generate_pure_image(data, FedoView.TIME_ENERGY, **kwargs),
        te_path
    )
    save_fig_to_file(
        generate_pure_image(data, FedoView.L_WD, **kwargs),
        lwd_path
    )

    return te_path, lwd_path


def generate_views_bytes(
        data: Dict[str, Any],
        **kwargs
) -> Tuple[bytes, bytes]:
    """
    Generate both Time-Energy and L-ωd views as PNG bytes.
    """
    te_bytes = save_fig_to_bytes(generate_pure_image(
        data, FedoView.TIME_ENERGY, **kwargs
    ))
    lwd_bytes = save_fig_to_bytes(generate_pure_image(
        data, FedoView.L_WD, **kwargs
    ))
    return te_bytes, lwd_bytes
