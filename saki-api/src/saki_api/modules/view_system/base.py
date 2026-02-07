"""
Base class for view coordinate mappers.

Provides a unified interface for converting coordinates between
different view representations (e.g., Time-Energy <-> L-Omegad).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple


class BaseViewMapper(ABC):
    """
    Abstract base class for view coordinate mappers.

    A view mapper is responsible for converting coordinates between
    different representations of the same data. For example, in FEDO
    satellite data, the same data can be viewed in Time-Energy space
    or in L-Omegad (L-shell vs drift frequency) space.

    Example:
        mapper = LUTViewMapper(lookup_table)

        # Convert pixel to physical coordinates
        phys_x, phys_y = mapper.pixel_to_physical(100, 200)

        # Convert physical to pixel coordinates
        px, py = mapper.physical_to_pixel(phys_x, phys_y)

        # Map a region to another view
        mapped_regions = mapper.map_region(
            {"x": 100, "y": 200, "width": 50, "height": 50},
            source_view="time-energy",
            target_view="L-omegad"
        )
    """

    @abstractmethod
    def pixel_to_physical(self, x: float, y: float) -> Tuple[float, float]:
        """
        Convert pixel coordinates to physical coordinates.

        Args:
            x: X pixel coordinate
            y: Y pixel coordinate

        Returns:
            Tuple of (physical_x, physical_y)
        """
        pass

    @abstractmethod
    def physical_to_pixel(self, phys_x: float, phys_y: float) -> Tuple[float, float]:
        """
        Convert physical coordinates to pixel coordinates.

        Args:
            phys_x: Physical X coordinate
            phys_y: Physical Y coordinate

        Returns:
            Tuple of (pixel_x, pixel_y)
        """
        pass

    @abstractmethod
    def map_region(
            self,
            region: Dict[str, Any],
            source_view: str,
            target_view: str,
    ) -> List[Dict[str, Any]]:
        """
        Map a region from source view to target view.

        Args:
            region: Region definition (e.g., bounding box)
            source_view: Source view name
            target_view: Target view name

        Returns:
            List of mapped regions (may be multiple if region splits)
        """
        pass

    @abstractmethod
    def get_physical_bounds(self) -> Dict[str, Tuple[float, float]]:
        """
        Get the physical coordinate bounds for all views.

        Returns:
            Dict mapping view names to (min, max) tuples
        """
        pass
