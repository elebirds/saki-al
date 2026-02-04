"""
FEDO (Flux of Energetic Electrons) data processing utilities.

This module provides the data processing pipeline for FEDO satellite data:
- Parsing FEDO text files
- Physics calculations (L-shell, drift frequency ωd)
- Visualization image generation (Time-Energy and L-ωd views)
- Coordinate lookup tables for bidirectional mapping

This module is part of the refactored annotation system.
Data format processing is now separated from annotation sync logic.
"""

from .config import FedoConfig, get_fedo_config
from .lookup import (
    generate_lookup_table,
    load_lookup_table,
    load_lookup_table_from_bytes,
    save_lookup_table_to_bytes,
    LookupTable
)
from .parser import load_fedo_data, load_fedo_data_from_bytes, parse_energy_bins
from .physics import calculate_physics_data, CONSTANTS
from .processor import FedoProcessor, FedoData
from .visualizer import generate_views, generate_views_bytes, generate_pure_image
from .obb_mapper import map_obb_annotations

__all__ = [
    # Main processor
    'FedoProcessor',
    'FedoData',
    # Config
    'FedoConfig',
    'get_fedo_config',
    # Parsing
    'load_fedo_data',
    'load_fedo_data_from_bytes',
    'parse_energy_bins',
    # Physics
    'calculate_physics_data',
    'CONSTANTS',
    # Visualization
    'generate_views',
    'generate_views_bytes',
    'generate_pure_image',
    # Lookup tables
    'generate_lookup_table',
    'load_lookup_table',
    'load_lookup_table_from_bytes',
    'save_lookup_table_to_bytes',
    'LookupTable',
    # OBB Mapper
    'map_obb_annotations',
]
