"""System module cross-context contracts."""

from __future__ import annotations

from typing import Protocol


class SystemSettingsReadContract(Protocol):
    async def get_value(self, key: str) -> object:
        """Read a system setting value."""
