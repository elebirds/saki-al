"""
Data Formats Module

This module contains data format processors for various dataset types.
These processors handle the parsing and transformation of raw data
into structured formats suitable for annotation.

Key submodules:
- fedo: FEDO satellite electron flux data processing
"""

from saki_api.modules.data_formats.fedo import (
    FedoProcessor,
    FedoData,
    FedoConfig,
    get_fedo_config,
    load_fedo_data,
    load_fedo_data_from_bytes,
    calculate_physics_data,
    generate_views_bytes,
    generate_lookup_table,
    load_lookup_table_from_bytes,
    LookupTable,
    map_obb_annotations,
)

__all__ = [
    # FEDO
    "FedoProcessor",
    "FedoData",
    "FedoConfig",
    "get_fedo_config",
    "load_fedo_data",
    "load_fedo_data_from_bytes",
    "calculate_physics_data",
    "generate_views_bytes",
    "generate_lookup_table",
    "load_lookup_table_from_bytes",
    "LookupTable",
    "map_obb_annotations",
]
