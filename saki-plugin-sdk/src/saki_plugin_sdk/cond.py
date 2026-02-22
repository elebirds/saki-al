"""
Expression-based visibility evaluation for plugin.yml.

This module provides a simple, safe expression evaluator for dynamic field
and option visibility in plugin configurations.

Inspired by Gemini's design pattern:
- ``ctx.*``: Project-level context (e.g., annotation_types)
- ``form.*``: Form field values (user input)
- Expression strings: ``"form.yolo_task === 'detect'"``

Example YAML::

    fields:
      - key: model_preset
        type: select
        options:
          - label: "YOLOv8n"
            value: "yolov8n.pt"
            visible: "form.yolo_task === 'detect'"
          - label: "YOLOv8n-OBB"
            value: "yolov8n-obb.pt"
            visible: "form.yolo_task === 'obb'"

Context dict format::

    {
        "annotationTypes": ["rect"],  # or "annotation_types"
        "fieldValues": {"yolo_task": "detect"},  # or "field_values"
    }
"""

from __future__ import annotations

from typing import Any


def _evaluate_expression(expr: str, context: dict[str, Any]) -> Any:
    """Safely evaluate a visible expression.

    Supports a restricted subset of Python/JS-like expressions:
    - Comparisons: ``===``, ``!==``, ``==``, ``!=``, ``<``, ``>``, ``<=``, ``>=``
    - Logical: ``and``, ``or``, ``&&``, ``||``
    - Method calls: ``ctx.annotation_types.includes('x')``
    - Attribute access: ``form.field_name``, ``ctx.var_name``

    Args:
        expr: Expression string to evaluate
        context: Context dict with ``annotationTypes`` and ``fieldValues`` namespaces

    Returns:
        Evaluation result (typically boolean for visibility)
    """
    if not expr or not isinstance(expr, str):
        return True

    expr = expr.strip()
    if not expr:
        return True

    try:
        # Normalize context keys (camelCase -> snake_case for internal use)
        normalized_context = {
            "annotation_types": context.get("annotation_types") or context.get("annotationTypes", []),
            "field_values": context.get("field_values") or context.get("fieldValues", {}),
        }

        # Convert JS-style operators to Python
        py_expr = expr.replace("===", "==").replace("!==", "!=")
        py_expr = py_expr.replace("&&", " and ").replace("||", " or ")

        # Build safe evaluation context
        safe_ctx = _build_safe_context(normalized_context)
        # Use eval with restricted globals
        return eval(py_expr, {"__builtins__": {}}, safe_ctx)
    except Exception as exc:
        import warnings
        warnings.warn(f"Failed to evaluate expression '{expr}': {exc}")
        return False


def _build_safe_context(context: dict[str, Any]) -> dict[str, Any]:
    """Build a safe evaluation context for expressions.

    Creates ``ctx`` and ``form`` namespaces.
    """
    annotation_types = context.get("annotation_types", [])

    # Create a list-like object with includes() method
    class SafeList(list):
        """List wrapper with includes() method for JS-like syntax."""

        def includes(self, value: Any) -> bool:
            """Check if value is in the list (case-insensitive for strings)."""
            return any(
                str(self_item).lower() == str(value).lower()
                for self_item in self
            )

    safe_list = SafeList(annotation_types)

    class ContextNamespace:
        """Project-level context (ctx.*)."""

        @property
        def annotation_types(self) -> SafeList:
            """Return annotation types list with includes() method."""
            return safe_list

    field_values = context.get("field_values", {})

    class FormNamespace:
        """Form values namespace (form.*)."""

        def __init__(self, values: dict[str, Any]):
            self._values = values

        def __getattr__(self, key: str) -> Any:
            return self._values.get(key, "")

    ctx_instance = ContextNamespace()
    form_instance = FormNamespace(field_values)

    return {
        "ctx": ctx_instance,
        "form": form_instance,
    }


def evaluate_visible(visible: str | bool | None, context: dict[str, Any]) -> bool:
    """Evaluate a ``visible`` expression or boolean.

    Args:
        visible: Visibility expression string or boolean value
        context: Context dict with ``annotationTypes`` and ``fieldValues``

    Returns:
        True if visible/expression is True, False otherwise

    Examples:
        >>> evaluate_visible("ctx.annotation_types.includes('rect')",
        ...                  {'annotationTypes': ['rect'], 'fieldValues': {}})
        True
        >>> evaluate_visible("form.yolo_task === 'detect'",
        ...                  {'annotationTypes': [], 'fieldValues': {'yolo_task': 'detect'}})
        True
    """
    if not visible:
        return True
    if isinstance(visible, bool):
        return visible
    if isinstance(visible, str):
        result = _evaluate_expression(visible, context)
        return bool(result)
    return True


def filter_options(
    options: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only the options whose ``visible`` expression is satisfied.

    Args:
        options: List of option dicts with optional ``visible`` attribute
        context: Context dict with ``annotationTypes`` and ``fieldValues``

    Returns:
        Filtered list of options
    """
    return [
        opt for opt in options
        if evaluate_visible(opt.get("visible"), context)
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "evaluate_visible",
    "filter_options",
]
