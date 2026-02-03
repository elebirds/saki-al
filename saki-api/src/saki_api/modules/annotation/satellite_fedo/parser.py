"""
FEDO data file parser.
Handles reading and parsing of satellite FEDO text data files.
"""

import io
from typing import Tuple, List

import numpy as np
import pandas as pd


def parse_energy_bins(lines: List[str]) -> np.ndarray:
    """
    Parse energy bin boundaries from file header.
    
    Args:
        lines: List of lines from the data file
        
    Returns:
        Array of energy channel centers in keV
    """
    try:
        energy_line = next(l for l in lines if "Energy [keV]" in l)
    except StopIteration:
        raise ValueError("未在文件头中找到 'Energy [keV]' 信息")

    content = energy_line.split("Energy [keV]")[-1]
    tokens = content.replace(',', ' ').split()
    boundaries = []
    for tok in tokens:
        try:
            boundaries.append(float(tok))
        except ValueError:
            continue

    boundaries_np = np.array(boundaries, dtype=float)
    if len(boundaries_np) < 2:
        raise ValueError("能道边界数量不足，无法计算能量中心")

    # Return geometric centers of energy bins
    return 0.5 * (boundaries_np[:-1] + boundaries_np[1:])


def load_fedo_data(file_path: str) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    """
    Load FEDO data from a text file.
    
    Args:
        file_path: Path to the FEDO data file
        
    Returns:
        Tuple of (DataFrame, energy_centers, energy_column_names)
    """
    with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
        lines = f.readlines()

    return _parse_fedo_lines(lines)


def load_fedo_data_from_bytes(file_bytes: bytes) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    """
    Load FEDO data from raw bytes (in-memory, no disk).
    
    Args:
        file_bytes: Raw file bytes
        
    Returns:
        Tuple of (DataFrame, energy_centers, energy_column_names)
    """
    text = file_bytes.decode("utf-8", errors="ignore")
    lines = text.splitlines(True)
    return _parse_fedo_lines(lines)


def _parse_fedo_lines(lines: List[str]) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    e_centers = parse_energy_bins(lines)

    # Find header line
    try:
        header_line = next(l for l in lines if l.strip().startswith("yyyy"))
    except StopIteration:
        raise ValueError("未找到表头 (yyyy...)")

    header_idx = lines.index(header_line)
    colnames = [c.strip() for c in header_line.split(',') if c.strip()]
    data_str = "".join(lines[header_idx + 1:])

    df = pd.read_csv(
        io.StringIO(data_str),
        header=None,
        names=colnames,
        sep=',',
        on_bad_lines='skip'
    )

    # Energy columns
    e_cols = [c for c in df.columns if c.startswith('E_') and c[2:].isdigit()]
    min_len = min(len(e_cols), len(e_centers))
    e_cols = e_cols[:min_len]
    e_centers = e_centers[:min_len]

    # Clean numeric values
    for col in e_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    for col in [c for c in df.columns if 'POS' in c or 'L_' in c]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Parse datetime
    df = df.copy()
    df['Datetime'] = pd.to_datetime(
        df[['yyyy', 'mn', 'dd', 'hh', 'mm', 'ss']].astype(str).agg('-'.join, axis=1),
        format='%Y-%m-%d-%H-%M-%S',
        errors='coerce'
    )

    return df, e_centers, e_cols
