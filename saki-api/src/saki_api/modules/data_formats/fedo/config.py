"""
FEDO configuration models and helpers.

This module centralizes FEDO processing configuration so it can be:
- Loaded from env/config files (prefixed with "fedo.")
- Overridden by runtime context (e.g., frontend or DB settings)
"""

from typing import Any, Dict, Optional, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict


class FedoConfig(BaseSettings):
    """
    FEDO processing configuration.

    Notes:
        - Env/config keys are prefixed with "fedo." (e.g., fedo.dpi=200)
        - Can be overridden by runtime context
    """

    figsize: Tuple[float, float] = (6.0, 4.0)
    dpi: int = 200
    max_file_size_mb: int = 50
    cmap: str = "jet"
    l_xlim: Optional[Tuple[float, float]] = None
    wd_ylim: Optional[Tuple[float, float]] = None

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_prefix="fedo.",
    )

    def to_prefixed_dict(self, prefix: str = "fedo.") -> Dict[str, Any]:
        """Export config using a prefixed-key format for external storage."""
        data = self.model_dump()
        return {f"{prefix}{k}": v for k, v in data.items()}


def _normalize_overrides(overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overrides:
        return {}

    normalized: Dict[str, Any] = {}

    # Accept nested overrides like {"fedo": {...}}
    fedo_nested = overrides.get("fedo")
    if isinstance(fedo_nested, dict):
        normalized.update(fedo_nested)

    # Accept flat overrides, including "fedo.xxx" keys
    for key, value in overrides.items():
        if key == "fedo":
            continue
        if key.startswith("fedo."):
            normalized[key[len("fedo."):]] = value
        else:
            normalized[key] = value

    return normalized


def get_fedo_config(overrides: Optional[Dict[str, Any]] = None) -> FedoConfig:
    """
    Get FEDO configuration with optional runtime overrides.

    Args:
        overrides: Optional dict of overrides. Supports:
            - {"fedo": {"dpi": 200}}
            - {"fedo.dpi": 200}
            - {"dpi": 200}

    Returns:
        FedoConfig
    """
    base = FedoConfig()
    update = _normalize_overrides(overrides)
    if not update:
        return base

    merged = base.model_dump()
    merged.update(update)
    return FedoConfig.model_validate(merged)
