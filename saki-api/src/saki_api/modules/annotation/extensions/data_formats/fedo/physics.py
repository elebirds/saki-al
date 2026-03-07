"""
Physical calculations for FEDO data.
Computes L-shell values and drift frequencies (ωd).
"""

from typing import Dict, List, Any

import numpy as np
import pandas as pd

# Physical constants
CONSTANTS = {
    'RE': 6371.2 * 1000,  # Earth radius (m)
    'ME': 8.0e15,  # Earth magnetic moment (T·m^3)
    'QE': 1.602e-19,  # Electron charge (C)
    'E0_KEV': 511.0,  # Electron rest energy (keV)
    'KEV_TO_J': 1.602e-16,  # keV to Joules
    'W_COR_RAD_H': 2 * np.pi / 24.0  # Earth rotation angular velocity (rad/hour)
}


def calculate_physics_data(
        df: pd.DataFrame,
        e_centers: np.ndarray,
        e_cols: List[str]
) -> Dict[str, Any]:
    """
    Calculate physical parameters from FEDO data.
    
    Args:
        df: DataFrame with raw FEDO data
        e_centers: Energy channel centers in keV
        e_cols: Names of energy columns
        
    Returns:
        Dictionary containing:
        - time: Datetime values (N,)
        - L: L-shell values (N,)
        - E: Energy centers in keV (M,)
        - Flux: Flux matrix (N, M)
        - Wd: Drift frequency matrix (N, M) in rad/hour
    """
    # Extract required columns
    try:
        x_col = next(c for c in df.columns if 'POS_GSEx' in c)
        y_col = next(c for c in df.columns if 'POS_GSEy' in c)
        z_col = next(c for c in df.columns if 'POS_GSEz' in c)
        l_col = next(c for c in df.columns if 'L_Dipole' in c)
    except StopIteration:
        raise KeyError("关键列缺失：POS_GSEx/POS_GSEy/POS_GSEz/L_Dipole")

    r_vec = df[[x_col, y_col, z_col]].values
    l_vals = df[l_col].values
    flux_matrix = df[e_cols].values
    time_vals = df['Datetime'].values if 'Datetime' in df.columns else np.arange(len(df))

    # Filter invalid points
    mask = (
            (l_vals >= 1.0) &
            np.isfinite(l_vals) &
            (np.linalg.norm(r_vec, axis=1) > 0) &
            np.isfinite(time_vals)
    )
    l_vals = l_vals[mask]
    r_vec = r_vec[mask]
    flux_matrix = flux_matrix[mask]
    time_vals = time_vals[mask]

    # Calculate geometric factor F(y)
    r_norm = np.linalg.norm(r_vec, axis=1)
    cos2 = np.clip(r_norm / (l_vals * CONSTANTS['RE']), 0, 1)  # ~ cos^2(lambda)
    sin2 = 1.0 - cos2
    y = ((cos2 ** 3) / np.sqrt(1 + 3 * sin2)) ** 0.5
    y_pow = y ** 0.75
    F_y = (5.520692 - 2.357194 * y + 1.279385 * y_pow) / (12 * (1.380173 - 0.639693 * y_pow))

    # Energy terms
    E_J = e_centers * CONSTANTS['KEV_TO_J']
    E0_J = CONSTANTS['E0_KEV'] * CONSTANTS['KEV_TO_J']
    gamma_term = (E_J * (E_J + 2 * E0_J)) / (E_J + E0_J)

    # Calculate drift frequency matrix (N x M)
    # Wd = C * L * gamma * F(y)
    prefactor = (3 * CONSTANTS['RE']) / (CONSTANTS['QE'] * CONSTANTS['ME'])
    wd_matrix_rad_s = prefactor * l_vals[:, None] * gamma_term[None, :] * F_y[:, None]
    wd_matrix = wd_matrix_rad_s * 3600 + CONSTANTS['W_COR_RAD_H']

    return {
        'time': time_vals,  # (N,)
        'L': l_vals,  # (N,)
        'E': e_centers,  # (M,)
        'Flux': flux_matrix,  # (N, M)
        'Wd': wd_matrix  # (N, M)
    }
