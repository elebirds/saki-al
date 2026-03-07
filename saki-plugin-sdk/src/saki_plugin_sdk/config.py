"""
Strongly-typed, schema-driven plugin configuration.

``PluginConfig`` is the SDK's unified configuration object.  It is
constructed automatically from ``config_schema`` (from ``plugin.yml``),
and provides:

* attribute-style access (``config.epochs``)
* type coercion driven by ``config_schema.fields[*].type``
* ``required`` / ``min`` / ``max`` / ``options`` validation
* passthrough of extra keys not declared in the schema
* Pydantic-based validation and serialization

Typical usage inside a plugin::

    config = PluginConfig.resolve(
        schema=config_schema,
        raw_config=raw_params,
        context={"annotationTypes": ["rect"]},
    )
    model = YOLO(config.model_preset, task=config.yolo_task)
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field
from pydantic import field_validator as pyd_field_validator

from saki_plugin_sdk.exceptions import PluginValidationError


# ---------------------------------------------------------------------------
# Schema field type definitions (Pydantic models)
# ---------------------------------------------------------------------------

class ConfigFieldProps(BaseModel):
    """UI component props (v-bind style).

    A flat mapping of UI attributes that can be directly bound to
    component props. This follows the pattern shown in Gemini's design
    where constraints are declared as props rather than separate fields.

    Examples::
        props: { min: 1, max: 5000, step: 1 }
        props: { placeholder: "Enter path...", rows: 3 }
    """
    min: float | None = None
    max: float | None = None
    step: float | None = None
    placeholder: str | None = None
    rows: int | None = None
    # Allow additional arbitrary props for extensibility
    model_config = {"extra": "allow"}


class ConfigFieldOption(BaseModel):
    """Option definition for select-type fields."""
    label: str
    value: Any
    visible: str | None = None


class ConfigField(BaseModel):
    """Configuration field definition from plugin.yml.

    New simplified pattern:
    - ``visible``: Expression string for dynamic visibility (e.g., "form.yolo_task === 'detect'")
    - ``props``: UI component props (min, max, step, placeholder, etc.)
    - ``options``: List of options for select fields, each with optional ``visible``
    """
    key: str
    label: str
    type: str  # 'integer', 'number', 'string', 'boolean', 'select', 'textarea', 'integer_array'
    required: bool = False
    # Field-level constraints (can also use props)
    min: float | None = None
    max: float | None = None
    default: Any = None
    description: str | None = None
    group: str | None = None
    depends_on: list[str] | None = None
    # Simplified UI pattern
    props: ConfigFieldProps | None = None
    visible: str | None = None  # Expression string for dynamic visibility
    options: list[ConfigFieldOption] | None = None


class ConfigSchema(BaseModel):
    """Configuration schema from plugin.yml."""
    title: str | None = None
    description: str | None = None
    fields: list[ConfigField] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

_COERCE_MAP: dict[str, type] = {
    "integer": int,
    "number": float,
    "boolean": bool,
    "string": str,
    "select": str,
    "textarea": str,
    "integer_array": list,
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
    if target is list and isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    try:
        return target(value)
    except (ValueError, TypeError):
        return value


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_field(key: str, value: Any, field_def: ConfigField) -> list[str]:
    """Validate a single field value against its schema definition.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    # --- required ---
    if field_def.required and (value is None or (isinstance(value, str) and not value.strip())):
        errors.append(f"config field '{key}' is required")

    if value is None:
        return errors

    # --- min / max ---
    field_type = field_def.type
    if field_type in ("integer", "number"):
        try:
            num_val = float(value)
        except (TypeError, ValueError):
            num_val = None
        if num_val is not None:
            if field_def.min is not None and num_val < field_def.min:
                errors.append(f"config field '{key}' = {num_val} is below minimum {field_def.min}")
            if field_def.max is not None and num_val > field_def.max:
                errors.append(f"config field '{key}' = {num_val} exceeds maximum {field_def.max}")

    # --- select options ---
    if field_type == "select":
        options = field_def.options or []
        if options:
            allowed = {
                str(o.value).strip().lower()
                for o in options
                if isinstance(o, ConfigFieldOption)
            }
            if allowed and str(value).strip().lower() not in allowed:
                errors.append(
                    f"config field '{key}' = {value!r} is not one of "
                    f"the allowed options: {sorted(allowed)}"
                )

    return errors


# ---------------------------------------------------------------------------
# PluginConfig
# ---------------------------------------------------------------------------

T = TypeVar("T", bound="PluginConfig")


class PluginConfig(BaseModel):
    """Immutable, attribute-accessible plugin configuration.

    Features:
    - Attribute-style access (Pydantic native)
    - Type validation (Pydantic automatic)
    - Serialization/deserialization (model_dump, model_validate)
    - JSON Schema export (model_json_schema)

    Parameters
    ----------
    **data : dict[str, Any]
        Fully resolved key-value pairs.

    Notes
    -----
    The model is configured with ``extra="allow"`` to support passthrough
    of extra keys not declared in the schema.
    """

    _schema: ConfigSchema | None = None

    model_config = {"extra": "allow"}

    # -------------------------------------------------------------------
    # Factory: the primary entry point
    # -------------------------------------------------------------------

    @classmethod
    def resolve(
        cls: type[T],
        *,
        schema: ConfigSchema,
        raw_config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> T:
        """Build a ``PluginConfig`` from schema + user overrides.

        Steps:
        1. Extract defaults from ``schema.fields`` (field-level defaults only)
        2. Override with ``raw_config``
        3. Coerce values to schema-declared types
        4. Optionally validate constraints

        Parameters
        ----------
        schema :
            The ``config_schema`` from plugin.yml.
        raw_config :
            User-supplied overrides (may be ``None``).
        context :
            Optional dict with ``"annotationTypes"`` for visible evaluation.
            Note: Context is NOT used for default resolution, only for
            runtime visibility evaluation in the UI.
        validate :
            If ``True`` (default), run constraint validation.

        Returns
        -------
        PluginConfig
            Resolved and validated configuration.
        """
        # 1. Build initial config from field-level defaults
        config: dict[str, Any] = {}

        for field in schema.fields:
            # Field-level default (scalar values only)
            if field.default is not None:
                config[field.key] = field.default

        # 2. Overlay user config
        if isinstance(raw_config, dict):
            config.update(raw_config)

        # 3. Coerce declared field types
        for field in schema.fields:
            if field.key in config:
                config[field.key] = _coerce(config[field.key], field.type)

        # 4. Validate
        if validate:
            all_errors: list[str] = []
            for field in schema.fields:
                all_errors.extend(_validate_field(field.key, config.get(field.key), field))
            if all_errors:
                raise PluginValidationError(
                    f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in all_errors)
                )

        result = cls(**config)
        object.__setattr__(result, "_schema", schema)
        return result

    @classmethod
    def from_manifest(
        cls: type[T],
        manifest: Any,  # PluginManifest (circular import avoidance)
        raw_config: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> T:
        """Convenience wrapper: build from a ``PluginManifest``.

        Parameters
        ----------
        manifest :
            PluginManifest instance with ``config_schema`` attribute.
        raw_config :
            User-supplied overrides.
        context :
            Optional dict with ``"annotation_types"`` etc.
        validate :
            If ``True`` (default), run constraint validation.
        """
        schema_dict = getattr(manifest, "config_schema", {})
        schema = ConfigSchema.model_validate(schema_dict)
        return cls.resolve(
            schema=schema,
            raw_config=raw_config,
            context=context,
            validate=validate,
        )

    @classmethod
    def merge(cls: type[T], *configs: T) -> T:
        """Merge multiple configs (later configs override earlier ones).

        Parameters
        ----------
        *configs : PluginConfig
            Variable number of PluginConfig instances to merge.

        Returns
        -------
        PluginConfig
            New instance with merged values.
        """
        merged: dict[str, Any] = {}
        schema: ConfigSchema | None = None

        for config in configs:
            merged.update(config.model_dump())
            if config._schema is not None:
                schema = config._schema

        result = cls(**merged)
        if schema is not None:
            object.__setattr__(result, "_schema", schema)
        return result

    # -------------------------------------------------------------------
    # Utility methods
    # -------------------------------------------------------------------

    def diff(self, other: PluginConfig) -> dict[str, tuple[Any, Any]]:
        """Compare this config with another, return changed fields.

        Parameters
        ----------
        other : PluginConfig
            Another PluginConfig instance to compare against.

        Returns
        -------
        dict[str, tuple[Any, Any]]
            Dictionary mapping field keys to (self_value, other_value) tuples.
        """
        diff_result: dict[str, tuple[Any, Any]] = {}
        all_keys = set(list(self.model_dump().keys()) + list(other.model_dump().keys()))
        for key in all_keys:
            self_val = getattr(self, key, None)
            other_val = getattr(other, key, None)
            if self_val != other_val:
                diff_result[key] = (self_val, other_val)
        return diff_result

    def validate_fields(self) -> list[str]:
        """Validate all fields against the schema.

        Returns
        -------
        list[str]
            List of error messages (empty if all valid).
        """
        if self._schema is None:
            return []
        errors: list[str] = []
        for field in self._schema.fields:
            errors.extend(_validate_field(field.key, getattr(self, field.key, None), field))
        return errors

    def get_grouped_fields(self) -> dict[str, list[ConfigField]]:
        """Return fields grouped by the ``group`` attribute.

        Returns
        -------
        dict[str, list[ConfigField]]
            Dictionary mapping group names to field lists.
            Fields without a group are placed under ``"default"``.
        """
        if self._schema is None:
            return {}
        groups: dict[str, list[ConfigField]] = {}
        for field in self._schema.fields:
            group = field.group or "default"
            if group not in groups:
                groups[group] = []
            groups[group].append(field)
        return groups

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the underlying mapping."""
        return self.model_dump()
