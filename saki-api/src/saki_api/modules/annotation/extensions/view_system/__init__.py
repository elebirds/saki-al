"""
View System Module

This module handles view coordinate mapping for multi-view datasets.
It provides abstractions for converting coordinates between different view representations.

Key components:
- BaseViewMapper: Abstract base class for view mappers
- LUTViewMapper: Lookup table-based coordinate mapper (for FEDO)
"""

from saki_api.modules.annotation.extensions.view_system.base import BaseViewMapper
from saki_api.modules.annotation.extensions.view_system.mappers.lut_mapper import LUTViewMapper

__all__ = [
    "BaseViewMapper",
    "LUTViewMapper",
]
