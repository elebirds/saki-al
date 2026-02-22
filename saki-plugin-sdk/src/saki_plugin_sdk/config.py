"""
Strongly-typed, schema-driven plugin configuration.

``PluginConfig`` is the SDK's unified configuration object.  It is
constructed automatically from ``config_schema`` + ``default_config``
(either from a ``PluginManifest`` or supplied directly), and provides:

* attribute-style access (``config.epochs``)
* type coercion driven by ``config_schema.fields[*].type``
* ``required`` / ``min`` / ``max`` / ``options`` validation
* conditional-default resolution (``cond`` protocol)
* passthrough of extra keys not declared in the schema

Typical usage inside a plugin::

    config = PluginConfig.resolve(
        default_config=self.default_request_config,
        config_schema=self.request_config_schema,
        raw_config=raw_params,
    )
    model = YOLO(config.model_preset, task=config.yolo_task)
"""

from __future__ import annotations

from typing import Any

from saki_plugin_sdk.cond import resolve_config_cond_values


# -----------------------------------------------------------------------
# Schema field type coercion
# -----------------------------------------------------------------------

_COERCE_MAP: dict[str, type] = {
    "integer": int,
    "number": float,
    "boolean": bool,
    "string": str,
    "select": str,
}


def _coerce(value: Any, field_type: str) -> Any:
    """Best-effort coercion of *value* according to *field_type*.

    Returns the original value unchanged if coercion is not applicable
    (e.g. ``None``, or the type is unknown).
    """
    if value is None:
        return value
    target = _COERCE_MAP.get(field_type)
    if target is None:
        return value
    if target is bool and isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    try:
        return target(value)
    except (ValueError, TypeError):
        return value


# -----------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------

def _validate_field(key: str, value: Any, field_def: dict[str, Any]) -> None:
    """Validate a single field value against its schema definition."""
    # --- required ---
    if field_def.get("required") and (value is None or (isinstance(value, str) and not value.strip())):
        raise ValueError(f"config field '{key}' is required")

    if value is None:
        return

    # --- min / max ---
    field_type = field_def.get("type", "string")
    if field_type in ("integer", "number"):
        num_val = value if isinstance(value, (int, float)) else None
        if num_val is not None:
            if "min" in field_def and num_val < field_def["min"]:
                raise ValueError(f"config field '{key}' = {num_val} is below minimum {field_def['min']}")
            if "max" in field_def and num_val > field_def["max"]:
                raise ValueError(f"config field '{key}' = {num_val} exceeds maximum {field_def['max']}")

    # --- select options (only declared-value options, ignoring cond) ---
    if field_type == "select":
        options = field_def.get("options")
        if options and isinstance(options, list):
            allowed = {
                str(o["value"]).strip().lower()
                for o in options
                if isinstance(o, dict) and "value" in o
            }
            if allowed and str(value).strip().lower() not in allowed:
                raise ValueError(
                    f"config field '{key}' = {value!r} is not one of "
                    f"the allowed options: {sorted(allowed)}"
                )


# -----------------------------------------------------------------------
# PluginConfig
# -----------------------------------------------------------------------

class PluginConfig:
    """Immutable, attribute-accessible plugin configuration.

    Parameters
    ----------
    data : dict[str, Any]
        Fully resolved key-value pairs.
    schema_fields : list[dict[str, Any]]
        The ``config_schema.fields`` list from ``plugin.yml`` (optional,
        used for repr / introspection).
    """

    __slots__ = ("_data", "_schema_fields")

    def __init__(self, data: dict[str, Any], schema_fields: list[dict[str, Any]] | None = None) -> None:
        object.__setattr__(self, "_data", dict(data))
        object.__setattr__(self, "_schema_fields", list(schema_fields or []))

    # --- attribute access ---

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"PluginConfig has no field '{name}'") from None

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("PluginConfig is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("PluginConfig is immutable")

    # --- dict-like helpers ---

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the underlying mapping."""
        return dict(self._data)

    def with_updates(self, **kwargs: Any) -> "PluginConfig":
        """Return a *new* ``PluginConfig`` with additional / overridden keys.

        The original instance is not mutated.
        """
        merged = dict(self._data)
        merged.update(kwargs)
        return PluginConfig(merged, schema_fields=self._schema_fields)

    # --- repr ---

    def __repr__(self) -> str:
        schema_keys = [f["key"] for f in self._schema_fields] if self._schema_fields else []
        parts: list[str] = []
        for key in schema_keys:
            if key in self._data:
                parts.append(f"{key}={self._data[key]!r}")
        extra = set(self._data) - set(schema_keys)
        for key in sorted(extra):
            parts.append(f"{key}={self._data[key]!r}")
        return f"PluginConfig({', '.join(parts)})"

    # -------------------------------------------------------------------
    # Factory: the primary entry point
    # -------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        *,
        default_config: dict[str, Any] | None = None,
        config_schema: dict[str, Any] | None = None,
        raw_config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> "PluginConfig":
        """Build a ``PluginConfig`` from schema + defaults + user overrides.

        Steps:
        1. Start with *default_config*.
        2. Overlay *raw_config* (user / API values).
        3. Resolve conditional-default lists (``cond`` protocol).
        4. Coerce values to schema-declared types.
        5. Optionally validate constraints.

        Parameters
        ----------
        default_config :
            Default values from ``plugin.yml`` ``default_config`` section.
        config_schema :
            The ``config_schema`` dict containing a ``fields`` list.
        raw_config :
            User-supplied overrides (may be ``None``).
        context :
            Optional dict with ``"annotation_types"`` etc. for cond.
        validate :
            If ``True`` (default), run constraint validation.
        """
        schema_fields: list[dict[str, Any]] = (
            config_schema.get("fields", [])
            if isinstance(config_schema, dict)
            else []
        )

        # 1. merge defaults + overrides
        merged: dict[str, Any] = dict(default_config) if default_config else {}
        if isinstance(raw_config, dict):
            merged.update(raw_config)

        # 2. resolve cond lists
        resolve_config_cond_values(merged, context)

        # 3. build a lookup for schema field defs
        field_defs: dict[str, dict[str, Any]] = {f["key"]: f for f in schema_fields if "key" in f}

        # 4. coerce declared fields
        for key, field_def in field_defs.items():
            if key in merged:
                merged[key] = _coerce(merged[key], field_def.get("type", "string"))

        # 5. validate
        if validate:
            for key, field_def in field_defs.items():
                _validate_field(key, merged.get(key), field_def)

        return cls(merged, schema_fields=schema_fields)

    @classmethod
    def from_manifest(
        cls,
        manifest: "PluginManifest",
        raw_config: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> "PluginConfig":
        """Convenience wrapper: build from a ``PluginManifest``."""
        from saki_plugin_sdk.manifest import PluginManifest as _PM  # noqa: F811

        return cls.resolve(
            default_config=manifest.default_config,
            config_schema=manifest.config_schema,
            raw_config=raw_config,
            context=context,
            validate=validate,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        schema_fields: list[dict[str, Any]] | None = None,
    ) -> "PluginConfig":
        """Wrap an already-resolved dict into a ``PluginConfig``.

        No coercion or validation is performed – the data is trusted
        to be already resolved (e.g. received from IPC serialisation).
        """
        return cls(data, schema_fields=schema_fields)
