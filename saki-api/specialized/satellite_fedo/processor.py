"""
Main processor for FEDO data files.
Orchestrates parsing, physics calculations, visualization, and lookup table generation.
"""

import os
import uuid
import pyarrow as pa
import pyarrow.parquet as pq
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

from .parser import load_fedo_data
from .physics import calculate_physics_data, get_data_bounds
from .visualizer import generate_views, get_image_dimensions
from .lookup import generate_lookup_table, LookupTable


class FedoProcessor:
    """
    Processor for FEDO data files.
    
    Handles the complete pipeline:
    1. Parse raw text file
    2. Calculate physics (L, ωd)
    3. Save processed data as parquet
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
        l_xlim: Tuple[float, float] = (1.2, 1.9),
        wd_ylim: Tuple[float, float] = (0.0, 4.0),
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
            - parquet_path: Path to processed data
            - time_energy_image_path: Path to Time-Energy view
            - l_wd_image_path: Path to L-ωd view
            - lookup_table_path: Path to lookup table
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
        
        # Step 3: Save processed data as parquet
        parquet_path = os.path.join(output_dir, "data.parquet")
        self._save_parquet(data, parquet_path)
        
        # Step 4: Generate images
        base_name = "view"
        te_path, lwd_path = generate_views(
            data, output_dir, base_name,
            dpi=dpi,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )
        
        # Step 5: Generate lookup table
        lookup_path = os.path.join(output_dir, "lookup.parquet")
        lookup = generate_lookup_table(data, lookup_path)
        
        # Collect metadata
        dimensions = get_image_dimensions(data)
        bounds = get_data_bounds(data)
        
        return {
            'sample_id': sample_id,
            'parquet_path': parquet_path,
            'time_energy_image_path': te_path,
            'l_wd_image_path': lwd_path,
            'lookup_table_path': lookup_path,
            'metadata': {
                'dimensions': dimensions,
                'bounds': bounds,
                'n_time': lookup.n_time,
                'n_energy': lookup.n_energy,
                'L_range': [lookup.L_min, lookup.L_max],
                'Wd_range': [lookup.Wd_min, lookup.Wd_max],
                'visualization_config': {
                    'dpi': dpi,
                    'l_xlim': l_xlim,
                    'wd_ylim': wd_ylim,
                }
            }
        }
    
    def _save_parquet(self, data: Dict[str, Any], output_path: str) -> None:
        """Save physics data to parquet file."""
        # Convert datetime to int64 for storage
        time_ns = data['time'].astype('datetime64[ns]').astype('int64')
        
        # Create table with essential data
        table = pa.table({
            'time_ns': time_ns,
            'L': data['L'],
        })
        
        # Add flux columns
        for j, e in enumerate(data['E']):
            table = table.append_column(f'flux_{j}', pa.array(data['Flux'][:, j]))
            table = table.append_column(f'wd_{j}', pa.array(data['Wd'][:, j]))
        
        pq.write_table(table, output_path, compression='snappy')
    
    def get_lookup_binary(self, sample_id: str) -> bytes:
        """
        Get lookup table in binary format for frontend.
        
        Args:
            sample_id: Sample identifier
            
        Returns:
            Binary data for lookup table
        """
        from .lookup import load_lookup_table
        
        lookup_path = os.path.join(self.base_storage_path, sample_id, "lookup.parquet")
        lookup = load_lookup_table(lookup_path)
        return lookup.to_binary()
