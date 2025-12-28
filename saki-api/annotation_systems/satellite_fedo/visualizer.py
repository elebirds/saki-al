"""
Visualization module for FEDO data.
Generates pure images for Time-Energy and L-ωd views.
"""

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.dates as mdates
from typing import Dict, Any, Tuple, Optional


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
    view: str,  # 'time_energy' or 'l_wd'
    output_path: str,
    dpi: int = 200,
    figsize: Tuple[float, float] = (6, 4),
    cmap: str = "jet",
    l_xlim: Optional[Tuple[float, float]] = None,
    wd_ylim: Optional[Tuple[float, float]] = None,
) -> str:
    """
    Generate a pure image (no axes, labels, or colorbar) for annotation overlay.
    
    Args:
        data: Physics data dictionary from calculate_physics_data
        view: 'time_energy' or 'l_wd'
        output_path: Path to save the image
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
    
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)

    if view == 'time_energy':
        # Time vs Energy view
        ax.pcolormesh(Time, E, Flux.T, norm=norm, cmap=cmap, shading='auto')
        ax.set_yscale('log')
        
    elif view == 'l_wd':
        # L vs ωd view with curvilinear grid
        L_grid = np.tile(L, (len(E), 1))  # (M, N)
        Wd_grid = Wd.T                      # (M, N)
        Z_data = Flux.T                     # (M, N)

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

        if wd_ylim is not None:
            ax.set_ylim(*wd_ylim)
        if l_xlim is not None:
            ax.set_xlim(*l_xlim)
    else:
        raise ValueError(f"Unknown view type: {view}")

    # Remove all decorations for pure image
    ax.set_axis_off()
    plt.tight_layout(pad=0.0)

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    fig.savefig(
        output_path,
        bbox_inches='tight',
        pad_inches=0.0,
        transparent=False,
        facecolor='white',
    )
    plt.close(fig)
    
    return output_path


def generate_views(
    data: Dict[str, Any],
    output_dir: str,
    base_name: str,
    dpi: int = 200,
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
    
    generate_pure_image(data, 'time_energy', te_path, dpi=dpi, **kwargs)
    generate_pure_image(data, 'l_wd', lwd_path, dpi=dpi, **kwargs)
    
    return te_path, lwd_path
