"""
FEDO (Flux of Energetic Electrons) data processing utilities.

This module provides the data processing pipeline for FEDO satellite data:
- Parsing FEDO text files
- Physics calculations (L-shell, drift frequency ωd)
- Visualization image generation (Time-Energy and L-ωd views)
- Coordinate lookup tables for bidirectional mapping

Note: The FedoHandler (annotation system handler) is in handlers/fedo.py
and uses these utilities for processing.
"""

from .processor import FedoProcessor
from .lookup import generate_lookup_table, load_lookup_table, LookupTable
from .parser import load_fedo_data, parse_energy_bins
from .physics import calculate_physics_data, CONSTANTS
from .visualizer import generate_views, generate_pure_image

__all__ = [
    # Main processor
    'FedoProcessor',
    # Parsing
    'load_fedo_data',
    'parse_energy_bins',
    # Physics
    'calculate_physics_data',
    'CONSTANTS',
    # Visualization
    'generate_views',
    'generate_pure_image',
    # Lookup tables
    'generate_lookup_table',
    'load_lookup_table',
    'LookupTable',
]
