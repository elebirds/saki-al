"""
Condition evaluation for plugin.yml ``cond`` directives.

Two condition types are supported:

1. ``annotation_types.subset_of``
   Evaluates to True when the project's ``enabled_annotation_types``
   is a *subset* of the given set.

   Example YAML::

       cond:
         annotation_types:
           subset_of: [rect, obb]

2. ``when_field``
   Evaluates to True when a sibling field has the specified value.

   Example YAML::

       cond:
         when_field:
           yolo_task: detect

Context dict expected shape::

    {
        "annotation_types": ["rect"],          # project context
        "field_values":     {"yolo_task": "obb"}  # current form values
    }
"""

from __future__ import annotations

from typing import Any


def evaluate_cond(cond: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    """Return *True* if *cond* is satisfied (or absent/empty).

    An absent or ``None`` condition is treated as *always True*.
    All sub-conditions must pass (logical AND).
    """
    if not cond or not isinstance(cond, dict):
        return True

    # --- annotation_types.subset_of ---
    ann_cond = cond.get("annotation_types")
    if isinstance(ann_cond, dict):
        subset_of = ann_cond.get("subset_of")
        if isinstance(subset_of, list):
            allowed = {str(v).strip().lower() for v in subset_of}
            project_types = _extract_annotation_types(context)
            if not project_types.issubset(allowed):
                return False

    # --- when_field ---
    when = cond.get("when_field")
    if isinstance(when, dict):
        field_values = context.get("field_values") or {}
        for field_key, expected in when.items():
            actual = field_values.get(field_key)
            if str(actual).strip().lower() != str(expected).strip().lower():
                return False

    return True


def resolve_conditional_default(
    entries: list[dict[str, Any]],
    context: dict[str, Any],
) -> Any:
    """Pick the first matching conditional default entry, or *fallback*.

    *entries* format (from plugin.yml ``default_config``)::

        [
            {"value": "detect", "cond": {"annotation_types": {"subset_of": ["rect"]}}},
            {"value": "obb", "fallback": true},
        ]

    Returns the ``value`` of the first entry whose ``cond`` passes, or the
    entry marked ``fallback: true``.  Returns ``None`` if nothing matches.
    """
    fallback_value: Any = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("fallback"):
            fallback_value = entry.get("value")
        cond = entry.get("cond")
        if evaluate_cond(cond, context):
            return entry.get("value")
    return fallback_value


def filter_options(
    options: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only the options whose ``cond`` is satisfied."""
    return [opt for opt in options if evaluate_cond(opt.get("cond"), context)]


def resolve_default_config(
    default_config: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a ``default_config`` section from plugin.yml.

    Scalar values are returned as-is.  List values are treated as
    conditional default entries and resolved via
    :func:`resolve_conditional_default`.
    """
    result: dict[str, Any] = {}
    for key, value in default_config.items():
        if isinstance(value, list):
            resolved = resolve_conditional_default(value, context)
            if resolved is not None:
                result[key] = resolved
        else:
            result[key] = value
    return result


def _is_cond_list(value: Any) -> bool:
    """Return True if *value* looks like a conditional-default list."""
    return (
        isinstance(value, list)
        and len(value) > 0
        and isinstance(value[0], dict)
        and "value" in value[0]
    )


def resolve_config_cond_values(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve any leftover conditional-default lists inside *config*.

    After merging ``default_request_config`` with ``raw_config``,
    some values may still be conditional-default lists (the user or
    API did not override them with scalar values).  This function
    resolves them in-place (two passes to handle ``when_field``
    dependencies on sibling values that are themselves conditional).

    *context* may contain ``"annotation_types"`` for project-level
    filtering.  ``field_values`` is populated automatically from
    the already-resolved scalars in *config*.
    """
    ctx: dict[str, Any] = dict(context) if context else {}

    # --- Pass 1: resolve entries that don't use when_field ---
    scalars: dict[str, Any] = {}
    pending_when_field: dict[str, list[dict[str, Any]]] = {}

    for key, value in config.items():
        if not _is_cond_list(value):
            scalars[key] = value
            continue

        # Check if any entry uses when_field
        uses_when_field = any(
            isinstance(e.get("cond"), dict) and "when_field" in e["cond"]
            for e in value
            if isinstance(e, dict)
        )
        if uses_when_field:
            # Defer to pass 2 — but try fallback first
            pending_when_field[key] = value
        else:
            resolved = resolve_conditional_default(value, ctx)
            if resolved is not None:
                scalars[key] = resolved
                config[key] = resolved

    # --- Pass 2: resolve when_field entries using pass-1 scalars ---
    ctx.setdefault("field_values", {})
    ctx["field_values"].update(scalars)

    for key, cond_list in pending_when_field.items():
        resolved = resolve_conditional_default(cond_list, ctx)
        if resolved is not None:
            config[key] = resolved

    return config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_annotation_types(context: dict[str, Any]) -> set[str]:
    """Extract the set of annotation type strings from context."""
    raw = context.get("annotation_types")
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(v).strip().lower() for v in raw}
    return set()
