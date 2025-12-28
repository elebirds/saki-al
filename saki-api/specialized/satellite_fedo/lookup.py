"""
Lookup table generation for coordinate mapping.
Pre-computes (L, ωd) values for each data index (i, j).
"""

import os
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple


@dataclass
class LookupTable:
    """
    Pre-computed lookup table for bidirectional coordinate mapping.
    
    For each index (i, j) in the N x M data matrix:
    - L[i]: L-shell value (same for all j at time i)
    - Wd[i, j]: Drift frequency value
    
    This enables fast conversion between:
    - Screen pixels → Data indices (i, j)
    - Data indices (i, j) → Physical coordinates (L, ωd)
    """
    n_time: int          # N - number of time points
    n_energy: int        # M - number of energy channels
    L: np.ndarray        # (N,) L-shell values
    Wd: np.ndarray       # (N, M) drift frequency matrix
    E: np.ndarray        # (M,) energy centers in keV
    time_stamps: np.ndarray  # (N,) datetime values as int64 (nanoseconds since epoch)
    
    # Physical bounds for normalization
    L_min: float
    L_max: float
    Wd_min: float
    Wd_max: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'n_time': self.n_time,
            'n_energy': self.n_energy,
            'L': self.L.tolist(),
            'Wd': self.Wd.tolist(),
            'E': self.E.tolist(),
            'time_stamps': self.time_stamps.tolist(),
            'L_min': self.L_min,
            'L_max': self.L_max,
            'Wd_min': self.Wd_min,
            'Wd_max': self.Wd_max,
        }
    
    def to_binary(self) -> bytes:
        """
        Convert to compact binary format for efficient frontend transfer.
        Format:
        - Header: n_time (4B), n_energy (4B), L_min (8B), L_max (8B), Wd_min (8B), Wd_max (8B)
        - L array: float32 (N * 4B)
        - Wd matrix: float32 (N * M * 4B)
        - E array: float32 (M * 4B)
        """
        import struct
        
        header = struct.pack(
            '<II4d',  # 2 uint32 + 4 float64
            self.n_time,
            self.n_energy,
            self.L_min,
            self.L_max,
            self.Wd_min,
            self.Wd_max,
        )
        
        L_bytes = self.L.astype(np.float32).tobytes()
        Wd_bytes = self.Wd.astype(np.float32).tobytes()
        E_bytes = self.E.astype(np.float32).tobytes()
        
        return header + L_bytes + Wd_bytes + E_bytes
    
    @classmethod
    def from_binary(cls, data: bytes) -> 'LookupTable':
        """Reconstruct lookup table from binary data."""
        import struct
        
        header_size = 2 * 4 + 4 * 8  # 2 uint32 + 4 float64
        n_time, n_energy, L_min, L_max, Wd_min, Wd_max = struct.unpack(
            '<II4d', data[:header_size]
        )
        
        offset = header_size
        L = np.frombuffer(data[offset:offset + n_time * 4], dtype=np.float32)
        offset += n_time * 4
        
        Wd = np.frombuffer(data[offset:offset + n_time * n_energy * 4], dtype=np.float32)
        Wd = Wd.reshape(n_time, n_energy)
        offset += n_time * n_energy * 4
        
        E = np.frombuffer(data[offset:offset + n_energy * 4], dtype=np.float32)
        
        return cls(
            n_time=n_time,
            n_energy=n_energy,
            L=L.astype(np.float64),
            Wd=Wd.astype(np.float64),
            E=E.astype(np.float64),
            time_stamps=np.array([]),  # Not stored in binary
            L_min=L_min,
            L_max=L_max,
            Wd_min=Wd_min,
            Wd_max=Wd_max,
        )


def generate_lookup_table(
    data: Dict[str, Any],
    output_path: Optional[str] = None
) -> LookupTable:
    """
    Generate pre-computed lookup table for coordinate mapping.
    
    Args:
        data: Physics data dictionary from calculate_physics_data
        output_path: Optional path to save as parquet file
        
    Returns:
        LookupTable object
    """
    L = data['L']
    Wd = data['Wd']
    E = data['E']
    time_vals = data['time']
    
    # Convert datetime to int64 nanoseconds
    time_stamps = time_vals.astype('datetime64[ns]').astype(np.int64)
    
    lookup = LookupTable(
        n_time=len(L),
        n_energy=len(E),
        L=L,
        Wd=Wd,
        E=E,
        time_stamps=time_stamps,
        L_min=float(np.nanmin(L)),
        L_max=float(np.nanmax(L)),
        Wd_min=float(np.nanmin(Wd)),
        Wd_max=float(np.nanmax(Wd)),
    )
    
    if output_path:
        save_lookup_table(lookup, output_path)
    
    return lookup


def save_lookup_table(lookup: LookupTable, output_path: str) -> None:
    """Save lookup table to parquet file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # PyArrow tables require all columns to have the same length.
    # We store arrays of different lengths by padding with NaN.
    n_time = lookup.n_time
    n_energy = lookup.n_energy
    max_len = max(n_time, n_energy, n_time * n_energy)
    
    # Pad arrays to max_len
    def pad_array(arr, target_len, dtype=np.float64):
        padded = np.full(target_len, np.nan, dtype=dtype)
        padded[:len(arr)] = arr
        return padded
    
    # Convert time_stamps (int64) separately - use 0 for padding
    time_stamps_padded = np.zeros(max_len, dtype=np.int64)
    time_stamps_padded[:n_time] = lookup.time_stamps
    
    table = pa.table({
        'L': pad_array(lookup.L, max_len),
        'E': pad_array(lookup.E, max_len),
        'time_stamps': time_stamps_padded,
        'Wd_flat': pad_array(lookup.Wd.flatten(), max_len),
        'n_time': np.array([lookup.n_time] + [0] * (max_len - 1), dtype=np.int32),
        'n_energy': np.array([lookup.n_energy] + [0] * (max_len - 1), dtype=np.int32),
        'L_min': pad_array(np.array([lookup.L_min]), max_len),
        'L_max': pad_array(np.array([lookup.L_max]), max_len),
        'Wd_min': pad_array(np.array([lookup.Wd_min]), max_len),
        'Wd_max': pad_array(np.array([lookup.Wd_max]), max_len),
    })
    
    pq.write_table(table, output_path, compression='snappy')


def load_lookup_table(file_path: str) -> LookupTable:
    """Load lookup table from parquet file."""
    table = pq.read_table(file_path)
    
    n_time = table['n_time'][0].as_py()
    n_energy = table['n_energy'][0].as_py()
    
    Wd_flat = table['Wd_flat'].to_numpy()
    Wd = Wd_flat[:n_time * n_energy].reshape(n_time, n_energy)
    
    return LookupTable(
        n_time=n_time,
        n_energy=n_energy,
        L=table['L'].to_numpy()[:n_time],
        Wd=Wd,
        E=table['E'].to_numpy()[:n_energy],
        time_stamps=table['time_stamps'].to_numpy()[:n_time],
        L_min=table['L_min'][0].as_py(),
        L_max=table['L_max'][0].as_py(),
        Wd_min=table['Wd_min'][0].as_py(),
        Wd_max=table['Wd_max'][0].as_py(),
    )


def indices_to_physical(
    lookup: LookupTable,
    indices: np.ndarray  # (K, 2) array of (i, j) pairs
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert data indices to physical coordinates.
    
    Args:
        lookup: LookupTable object
        indices: Array of (time_idx, energy_idx) pairs
        
    Returns:
        Tuple of (L_values, Wd_values) arrays
    """
    i = indices[:, 0].astype(int)
    j = indices[:, 1].astype(int)
    
    # Clamp to valid range
    i = np.clip(i, 0, lookup.n_time - 1)
    j = np.clip(j, 0, lookup.n_energy - 1)
    
    L_values = lookup.L[i]
    Wd_values = lookup.Wd[i, j]
    
    return L_values, Wd_values
