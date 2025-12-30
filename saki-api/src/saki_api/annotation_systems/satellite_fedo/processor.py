"""
Main processor for FEDO data files.
Orchestrates parsing, physics calculations, visualization, and lookup table generation.
"""

import os
import uuid
from typing import Dict, Any, Tuple, Optional

import numpy as np

from .lookup import generate_lookup_table
from .parser import load_fedo_data
from .physics import calculate_physics_data
from .visualizer import generate_views


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

    def __init__(self, base_storage_path: str):
        """
        Initialize processor.
        
        Args:
            base_storage_path: Base directory for storing processed data
        """
        self.base_storage_path = base_storage_path

    def process_file(
            self,
            file_path: str,
            sample_id: Optional[str] = None,
            dpi: int = 200,
            l_xlim: Optional[Tuple[float, float]] = None,
            wd_ylim: Optional[Tuple[float, float]] = None,
    ) -> Dict[str, Any]:
        """
        Process a FEDO data file completely.
        
        Args:
            file_path: Path to the raw FEDO text file
            sample_id: Optional sample ID (will be generated if not provided)
            dpi: Image resolution
            l_xlim: L-shell axis limits
            wd_ylim: Drift frequency axis limits
            
        Returns:
            Dictionary with paths and metadata:
            - sample_id: Unique identifier
            - data_path: Path to processed data (npz)
            - time_energy_image_path: Path to Time-Energy view
            - l_wd_image_path: Path to L-ωd view
            - lookup_table_path: Path to lookup table (npz)
            - metadata: Data dimensions and bounds
        """
        if sample_id is None:
            sample_id = str(uuid.uuid4())

        # Create output directory
        output_dir = os.path.join(self.base_storage_path, sample_id)
        os.makedirs(output_dir, exist_ok=True)

        # Step 1: Parse raw data
        df, e_centers, e_cols = load_fedo_data(file_path)

        # Step 2: Calculate physics
        data = calculate_physics_data(df, e_centers, e_cols)

        # 如果未指定范围，则从数据中计算实际范围
        if l_xlim is None:
            L_valid = data['L'][np.isfinite(data['L'])]
            if len(L_valid) > 0:
                l_xlim = (float(np.nanmin(L_valid)), float(np.nanmax(L_valid)))
            else:
                l_xlim = (1.0, 2.0)  # 默认范围作为后备
        
        if wd_ylim is None:
            Wd_valid = data['Wd'][np.isfinite(data['Wd'])]
            if len(Wd_valid) > 0:
                wd_ylim = (float(np.nanmin(Wd_valid)), float(np.nanmax(Wd_valid)))
            else:
                wd_ylim = (0.0, 4.0)  # 默认范围作为后备

        # Step 3: Save processed data as npz
        data_path = os.path.join(output_dir, "data.npz")
        self._save_data_npz(data, data_path)

        # Step 4: Generate images
        base_name = "view"
        # TODO: 需要根据数据实际尺寸
        # 获取图像尺寸（与 visualizer 中的默认值一致）
        figsize = (6.0, 4.0)  # 默认图像尺寸（英寸）
        image_width = figsize[0] * dpi
        image_height = figsize[1] * dpi
        
        te_path, lwd_path = generate_views(
            data, output_dir, base_name,
            dpi=dpi,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )

        # Step 5: Generate lookup table (使用新的高效矢量化实现)
        lookup_path = os.path.join(output_dir, "lookup.npz")
        lookup = generate_lookup_table(
            data,
            lookup_path,
            image_width=image_width,
            image_height=image_height,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )

        return {
            'sample_id': sample_id,
            'data_path': data_path,
            'time_energy_image_path': te_path,
            'l_wd_image_path': lwd_path,
            'lookup_table_path': lookup_path,
            'metadata': {
                'n_time': lookup.n_time,
                'n_energy': lookup.n_energy,
                'L_range': [float(np.nanmin(data['L'])), float(np.nanmax(data['L']))],
                'Wd_range': [float(np.nanmin(data['Wd'])), float(np.nanmax(data['Wd']))],
                'visualization_config': {
                    'dpi': dpi,
                    'l_xlim': l_xlim,
                    'wd_ylim': wd_ylim,
                }
            }
        }

    def _save_data_npz(self, data: Dict[str, Any], output_path: str) -> None:
        """Save physics data to npz file."""
        # Convert datetime to int64 for storage
        time_ns = data['time'].astype('datetime64[ns]').astype('int64')
        
        # Save all data arrays to npz
        np.savez_compressed(
            output_path,
            time_ns=time_ns,
            L=data['L'],
            E=data['E'],
            Flux=data['Flux'],
            Wd=data['Wd'],
        )

    def get_lookup_binary(self, sample_id: str) -> bytes:
        """
        Get lookup table in binary format for frontend.
        
        Args:
            sample_id: Sample identifier
            
        Returns:
            Binary data for lookup table
        """
        from .lookup import load_lookup_table

        lookup_path = os.path.join(self.base_storage_path, sample_id, "lookup.npz")
        lookup = load_lookup_table(lookup_path)
        return lookup.to_binary()
