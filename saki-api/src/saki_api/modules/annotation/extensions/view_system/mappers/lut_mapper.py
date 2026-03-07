"""
Lookup table-based view mapper.

Uses pre-computed lookup tables for fast coordinate conversion between views.
Used by FEDO dual-view annotation system.
"""

from typing import Any, Dict, List, Tuple

import numpy as np

from saki_api.modules.annotation.extensions.data_formats.fedo.enum import FedoView
from saki_api.modules.annotation.extensions.data_formats.fedo.lookup import LookupTable
from saki_api.modules.annotation.extensions.view_system.base import BaseViewMapper


class LUTViewMapper(BaseViewMapper):
    """
    View mapper based on lookup tables.

    This mapper uses pre-computed lookup tables that store the
    physical coordinates corresponding to each pixel in each view.

    The lookup tables allow for fast bidirectional coordinate conversion:
    - Time-Energy view <-> Physical (Time, Energy)
    - L-Omegad view <-> Physical (L, Wd)
    """

    # View identifiers
    VIEW_TIME_ENERGY = FedoView.TIME_ENERGY.value
    VIEW_L_OMEGAD = FedoView.L_OMEGAD.value

    def __init__(self, lookup_table: LookupTable):
        """
        Initialize the mapper with a lookup table.

        Args:
            lookup_table: LookupTable with lut_te and lut_lw arrays
        """
        self.lookup = lookup_table

    def pixel_to_physical_te(self, x: float, y: float, image_width: float, image_height: float) -> Tuple[float, float]:
        """
        Convert pixel coordinates to Time-Energy physical coordinates.

        Args:
            x: X pixel coordinate
            y: Y pixel coordinate
            image_width: Image width in pixels
            image_height: Image height in pixels

        Returns:
            Tuple of (time_val, energy)
        """
        # Normalize pixel coordinates to [0, 1]
        x_norm = x / image_width
        y_norm = y / image_height

        # Time: linear mapping from [0, 1] to [0, n_time-1]
        time_idx = x_norm * (self.lookup.n_time - 1)
        time_idx = np.clip(time_idx, 0, self.lookup.n_time - 1)

        # Energy: log scale mapping from [0, 1] to energy range
        E_min = self.lookup.E.min()
        E_max = self.lookup.E.max()
        log_E_min = np.log10(E_min)
        log_E_max = np.log10(E_max)
        log_E = log_E_min + (1 - y_norm) * (log_E_max - log_E_min)  # y=0 is top (max energy)
        E = 10 ** log_E

        # Get time value (convert index to datetime)
        time_idx_int = int(np.clip(time_idx, 0, self.lookup.n_time - 1))
        time_ns = self.lookup.time_stamps[time_idx_int]
        time_val = time_ns  # Keep as nanoseconds

        return time_val, E

    def pixel_to_physical_lwd(
            self,
            x: float,
            y: float,
            image_width: float,
            image_height: float,
            l_xlim: Tuple[float, float],
            wd_ylim: Tuple[float, float],
    ) -> Tuple[float, float]:
        """
        Convert pixel coordinates to L-Omegad physical coordinates.

        Args:
            x: X pixel coordinate
            y: Y pixel coordinate
            image_width: Image width in pixels
            image_height: Image height in pixels
            l_xlim: L-axis limits (min, max)
            wd_ylim: Wd-axis limits (min, max)

        Returns:
            Tuple of (L, Wd)
        """
        x_norm = x / image_width
        y_norm = y / image_height

        # L: linear mapping
        L = l_xlim[0] + x_norm * (l_xlim[1] - l_xlim[0])

        # Wd: linear mapping (y=0 is bottom, y=1 is top)
        Wd = wd_ylim[0] + (1 - y_norm) * (wd_ylim[1] - wd_ylim[0])

        return L, Wd

    def physical_to_pixel_te(
            self,
            time_val: float,
            E: float,
            image_width: float,
            image_height: float,
    ) -> Tuple[float, float]:
        """
        Convert Time-Energy physical coordinates to pixel coordinates.

        Args:
            time_val: Time value (nanoseconds)
            E: Energy value
            image_width: Image width in pixels
            image_height: Image height in pixels

        Returns:
            Tuple of (pixel_x, pixel_y)
        """
        # Find closest time index
        time_idx = np.searchsorted(self.lookup.time_stamps, time_val)
        time_idx = np.clip(time_idx, 0, self.lookup.n_time - 1)
        x_norm = time_idx / (self.lookup.n_time - 1) if self.lookup.n_time > 1 else 0

        # Energy: log scale
        E_min = self.lookup.E.min()
        E_max = self.lookup.E.max()
        log_E_min = np.log10(E_min)
        log_E_max = np.log10(E_max)
        log_E = np.log10(np.clip(E, E_min, E_max))
        y_norm = 1 - (log_E - log_E_min) / (log_E_max - log_E_min) if log_E_max > log_E_min else 0.5

        return x_norm * image_width, y_norm * image_height

    def physical_to_pixel_lwd(
            self,
            L: float,
            Wd: float,
            image_width: float,
            image_height: float,
            l_xlim: Tuple[float, float],
            wd_ylim: Tuple[float, float],
    ) -> Tuple[float, float]:
        """
        Convert L-Omegad physical coordinates to pixel coordinates.

        Args:
            L: L-shell value
            Wd: Drift frequency value
            image_width: Image width in pixels
            image_height: Image height in pixels
            l_xlim: L-axis limits (min, max)
            wd_ylim: Wd-axis limits (min, max)

        Returns:
            Tuple of (pixel_x, pixel_y)
        """
        # L: linear mapping
        x_norm = (L - l_xlim[0]) / (l_xlim[1] - l_xlim[0]) if l_xlim[1] > l_xlim[0] else 0.5
        x_norm = np.clip(x_norm, 0, 1)

        # Wd: linear mapping (y=0 is bottom)
        y_norm = 1 - (Wd - wd_ylim[0]) / (wd_ylim[1] - wd_ylim[0]) if wd_ylim[1] > wd_ylim[0] else 0.5
        y_norm = np.clip(y_norm, 0, 1)

        return x_norm * image_width, y_norm * image_height

    # ==================== BaseViewMapper Interface ====================

    def pixel_to_physical(
            self,
            x: float,
            y: float,
            view: str = FedoView.TIME_ENERGY.value,
            **kwargs
    ) -> Tuple[float, float]:
        """
        Convert pixel coordinates to physical coordinates.

        Args:
            x: X pixel coordinate
            y: Y pixel coordinate
            view: View name ("time-energy" or "L-omegad")
            **kwargs: Additional parameters (image_width, image_height, l_xlim, wd_ylim)

        Returns:
            Tuple of (physical_x, physical_y)
        """
        image_width = kwargs.get("image_width", self.lookup.n_time)
        image_height = kwargs.get("image_height", self.lookup.n_energy)

        view_key = FedoView.parse(view).value
        if view_key == self.VIEW_TIME_ENERGY:
            return self.pixel_to_physical_te(x, y, image_width, image_height)
        elif view_key == self.VIEW_L_OMEGAD:
            l_xlim = kwargs.get("l_xlim", (1.2, 1.9))
            wd_ylim = kwargs.get("wd_ylim", (0.0, 4.0))
            return self.pixel_to_physical_lwd(x, y, image_width, image_height, l_xlim, wd_ylim)
        else:
            raise ValueError(f"Unknown view: {view}")

    def physical_to_pixel(
            self,
            phys_x: float,
            phys_y: float,
            view: str = FedoView.TIME_ENERGY.value,
            **kwargs
    ) -> Tuple[float, float]:
        """
        Convert physical coordinates to pixel coordinates.

        Args:
            phys_x: Physical X coordinate
            phys_y: Physical Y coordinate
            view: View name ("time-energy" or "L-omegad")
            **kwargs: Additional parameters (image_width, image_height, l_xlim, wd_ylim)

        Returns:
            Tuple of (pixel_x, pixel_y)
        """
        image_width = kwargs.get("image_width", self.lookup.n_time)
        image_height = kwargs.get("image_height", self.lookup.n_energy)

        view_key = FedoView.parse(view).value
        if view_key == self.VIEW_TIME_ENERGY:
            return self.physical_to_pixel_te(phys_x, phys_y, image_width, image_height)
        elif view_key == self.VIEW_L_OMEGAD:
            l_xlim = kwargs.get("l_xlim", (1.2, 1.9))
            wd_ylim = kwargs.get("wd_ylim", (0.0, 4.0))
            return self.physical_to_pixel_lwd(phys_x, phys_y, image_width, image_height, l_xlim, wd_ylim)
        else:
            raise ValueError(f"Unknown view: {view}")

    def map_region(
            self,
            region: Dict[str, Any],
            source_view: str,
            target_view: str,
            **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Map a region from source view to target view.

        This method uses the OBB mapper for accurate region mapping
        with time-gap segmentation.

        Args:
            region: Region definition (bounding box with x, y, width, height, rotation)
            source_view: Source view name
            target_view: Target view name
            **kwargs: Additional parameters

        Returns:
            List of mapped regions (may be multiple if region splits)
        """
        # This is handled by DualViewSyncHandler using map_obb_annotations
        # This method is provided for interface compatibility
        raise NotImplementedError("Use DualViewSyncHandler._generate_mapped_annotations instead")

    def get_physical_bounds(self) -> Dict[str, Tuple[float, float]]:
        """
        Get the physical coordinate bounds for all views.

        Returns:
            Dict mapping view names to (min, max) tuples
        """
        E_min = self.lookup.E.min()
        E_max = self.lookup.E.max()

        return {
            self.VIEW_TIME_ENERGY: (
                float(self.lookup.time_stamps[0]),
                float(self.lookup.time_stamps[-1])
            ),
            self.VIEW_L_OMEGAD: (1.2, 1.9),  # Default L range
        }
