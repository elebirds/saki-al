"""
Satellite FEDO (Flux of Energetic Electrons) data processing module.

This module handles:
- Parsing FEDO data files
- Physical calculations (L-shell, drift frequency ωd)
- Generating visualization images (Time-Energy and L-ωd views)
- Pre-computing coordinate lookup tables for bidirectional mapping
"""

from .parser import load_fedo_data, parse_energy_bins
from .physics import calculate_physics_data, CONSTANTS
from .visualizer import generate_views, generate_pure_image
from .lookup import generate_lookup_table, LookupTable

__all__ = [
    'load_fedo_data',
    'parse_energy_bins',
    'calculate_physics_data',
    'CONSTANTS',
    'generate_views',
    'generate_pure_image',
    'generate_lookup_table',
    'LookupTable',
]
