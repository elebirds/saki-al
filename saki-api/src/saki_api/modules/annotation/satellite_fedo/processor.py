"""
Main processor for FEDO data files.
Orchestrates parsing, physics calculations, visualization, and lookup table generation.
"""
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional

import numpy as np

from .config import FedoConfig
from .lookup import generate_lookup_table, save_lookup_table_to_bytes
from .parser import load_fedo_data, load_fedo_data_from_bytes
from .physics import calculate_physics_data
from .visualizer import generate_views_bytes


@dataclass
class FedoData:
    """
    Processed FEDO data container.
    """
    data_bytes: bytes
    time_energy_image_bytes: bytes
    l_wd_image_bytes: bytes
    lookup_table_bytes: bytes
    metadata: Dict[str, Any]


def _resolve_ranges(
        data: Dict[str, Any],
        l_xlim: Optional[Tuple[float, float]],
        wd_ylim: Optional[Tuple[float, float]],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    if l_xlim is None:
        L_valid = data['L'][np.isfinite(data['L'])]
        l_xlim = (float(np.nanmin(L_valid)), float(np.nanmax(L_valid))) if len(L_valid) > 0 else (1.0, 2.0)

    if wd_ylim is None:
        Wd_valid = data['Wd'][np.isfinite(data['Wd'])]
        wd_ylim = (float(np.nanmin(Wd_valid)), float(np.nanmax(Wd_valid))) if len(Wd_valid) > 0 else (0.0, 4.0)

    return l_xlim, wd_ylim


def _build_metadata(
        data: Dict[str, Any],
        lookup: Any,
        config: FedoConfig,
        l_xlim: Tuple[float, float],
        wd_ylim: Tuple[float, float]
) -> Dict[str, Any]:
    return {
        'n_time': lookup.n_time,
        'n_energy': lookup.n_energy,
        'L_range': [float(np.nanmin(data['L'])), float(np.nanmax(data['L']))],
        'Wd_range': [float(np.nanmin(data['Wd'])), float(np.nanmax(data['Wd']))],
        'visualization_config': {
            'dpi': config.dpi,
            'figsize': config.figsize,
            'cmap': config.cmap,
            'l_xlim': l_xlim,
            'wd_ylim': wd_ylim,
        }
    }


def _save_data_npz_to_bytes(data: Dict[str, Any]) -> bytes:
    import io
    buf = io.BytesIO()
    time_ns = data['time'].astype('datetime64[ns]').astype('int64')
    np.savez_compressed(
        buf,
        time_ns=time_ns,
        L=data['L'],
        E=data['E'],
        Flux=data['Flux'],
        Wd=data['Wd'],
    )
    buf.seek(0)
    return buf.read()


class FedoProcessor:
    """
    Processor for FEDO data files.
    
    Handles the complete pipeline:
    1. Parse raw text file
    2. Calculate physics (L, ωd)
    3. Save processed data as npz
    4. Generate visualization images
    5. Generate coordinate lookup table
    """

    def process_data(
            self,
            df,
            e_centers,
            e_cols,
            config: FedoConfig,
    ) -> FedoData:
        """
        Process FEDO data already loaded into memory.

        The processor does not care where the data came from or where it will be saved.

        Args:
            df: Parsed FEDO dataframe
            e_centers: Energy centers
            e_cols: Energy column names
            config: FEDO configuration (visualization, limits, etc.)
            sample_id: Optional sample ID (generated if not provided)

        Returns:
            Dictionary with bytes for data, images, and lookup table
        """
        # Step 1: Calculate physics
        data = calculate_physics_data(df, e_centers, e_cols)

        # Resolve ranges
        l_xlim, wd_ylim = _resolve_ranges(data, config.l_xlim, config.wd_ylim)

        # Step 2: Build data.npz bytes
        data_bytes = _save_data_npz_to_bytes(data)

        # Step 3: Generate images as bytes
        image_width = config.figsize[0] * config.dpi
        image_height = config.figsize[1] * config.dpi

        te_bytes, lwd_bytes = generate_views_bytes(
            data,
            dpi=config.dpi,
            figsize=config.figsize,
            cmap=config.cmap,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )

        # Step 4: Generate lookup table bytes
        lookup = generate_lookup_table(
            data,
            output_path=None,
            image_width=image_width,
            image_height=image_height,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )
        lookup_bytes = save_lookup_table_to_bytes(lookup)

        return FedoData(
            data_bytes=data_bytes,
            time_energy_image_bytes=te_bytes,
            l_wd_image_bytes=lwd_bytes,
            lookup_table_bytes=lookup_bytes,
            metadata=_build_metadata(data, lookup, config, l_xlim, wd_ylim)
        )

    def process_file(
            self,
            file_path: str,
            config: FedoConfig,
    ) -> FedoData:
        """
        Process a FEDO data file from disk into in-memory outputs.

        Note: This is a thin wrapper around process_data.
        """
        df, e_centers, e_cols = load_fedo_data(file_path)
        return self.process_data(
            df=df,
            e_centers=e_centers,
            e_cols=e_cols,
            config=config,
        )

    def process_bytes(
            self,
            file_bytes: bytes,
            config: FedoConfig,
    ) -> FedoData:
        """
        Process a FEDO data file entirely in memory (no disk).

        Note: This is a thin wrapper around process_data.
        """
        df, e_centers, e_cols = load_fedo_data_from_bytes(file_bytes)
        return self.process_data(
            df=df,
            e_centers=e_centers,
            e_cols=e_cols,
            config=config,
        )
