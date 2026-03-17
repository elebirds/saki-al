from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.project.api.export import (
    PredictionsJSONFilterGroup,
    PredictionsJSONFilterNode,
    PredictionsJSONFilterRule,
)

_ALLOWED_SCALAR_FIELDS = {
    "annotation.id": "uuid",
    "annotation.label_id": "uuid",
    "annotation.label_name": "string",
    "annotation.type": "string",
    "annotation.source": "string",
    "annotation.confidence": "number",
}
_NUMERIC_OPERATORS = {"gt", "gte", "lt", "lte"}
_SET_OPERATORS = {"in", "not_in"}
_EXISTENCE_OPERATORS = {"exists", "not_exists"}
_MISSING = object()


def filter_predictions_json_annotations(
    *,
    annotations: Sequence[Annotation],
    label_name_by_id: Mapping[uuid.UUID, str],
    filter_node: PredictionsJSONFilterNode | None,
) -> list[Annotation]:
    if filter_node is None:
        return list(annotations)

    _validate_filter_node(filter_node)
    return [
        annotation
        for annotation in annotations
        if _evaluate_filter_node(
            filter_node=filter_node,
            annotation=annotation,
            label_name_by_id=label_name_by_id,
        )
    ]


def _validate_filter_node(filter_node: PredictionsJSONFilterNode) -> None:
    if isinstance(filter_node, PredictionsJSONFilterGroup):
        for item in filter_node.items:
            _validate_filter_node(item)
        return

    field_kind = _field_kind(filter_node.field)
    operator = str(filter_node.operator)

    if operator in _SET_OPERATORS:
        if not isinstance(filter_node.value, list):
            raise BadRequestAppException(
                f"predictions_json filter field={filter_node.field} operator={operator} requires list value"
            )
        for item in filter_node.value:
            _validate_value_type(field=filter_node.field, field_kind=field_kind, value=item, operator=operator)
        return

    if operator in _EXISTENCE_OPERATORS:
        return

    _validate_value_type(
        field=filter_node.field,
        field_kind=field_kind,
        value=filter_node.value,
        operator=operator,
    )


def _field_kind(field: str) -> str:
    normalized = str(field or "").strip()
    if normalized in _ALLOWED_SCALAR_FIELDS:
        return _ALLOWED_SCALAR_FIELDS[normalized]
    if normalized.startswith("annotation.attrs.") and normalized != "annotation.attrs.":
        return "dynamic"
    raise BadRequestAppException(f"predictions_json filter does not support field={normalized}")


def _validate_value_type(*, field: str, field_kind: str, value: Any, operator: str) -> None:
    if operator in _NUMERIC_OPERATORS:
        if not _is_number(value):
            raise BadRequestAppException(
                f"predictions_json filter field={field} operator={operator} requires numeric value"
            )
        return

    if field_kind == "uuid":
        if not isinstance(value, (str, uuid.UUID)):
            raise BadRequestAppException(
                f"predictions_json filter field={field} operator={operator} requires string uuid value"
            )
        return

    if field_kind == "string":
        if not isinstance(value, str):
            raise BadRequestAppException(
                f"predictions_json filter field={field} operator={operator} requires string value"
            )
        return

    if field_kind == "number":
        if not _is_number(value):
            raise BadRequestAppException(
                f"predictions_json filter field={field} operator={operator} requires numeric value"
            )


def _evaluate_filter_node(
    *,
    filter_node: PredictionsJSONFilterNode,
    annotation: Annotation,
    label_name_by_id: Mapping[uuid.UUID, str],
) -> bool:
    if isinstance(filter_node, PredictionsJSONFilterGroup):
        if filter_node.op == "and":
            return all(
                _evaluate_filter_node(
                    filter_node=item,
                    annotation=annotation,
                    label_name_by_id=label_name_by_id,
                )
                for item in filter_node.items
            )
        return any(
            _evaluate_filter_node(
                filter_node=item,
                annotation=annotation,
                label_name_by_id=label_name_by_id,
            )
            for item in filter_node.items
        )

    resolved = _resolve_field_value(
        annotation=annotation,
        label_name_by_id=label_name_by_id,
        field=filter_node.field,
    )
    operator = str(filter_node.operator)

    if operator == "exists":
        return resolved is not _MISSING
    if operator == "not_exists":
        return resolved is _MISSING
    if resolved is _MISSING:
        return False

    field_kind = _field_kind(filter_node.field)
    target = filter_node.value
    if operator == "eq":
        return _normalize_value(resolved, field_kind=field_kind) == _normalize_value(target, field_kind=field_kind)
    if operator == "neq":
        return _normalize_value(resolved, field_kind=field_kind) != _normalize_value(target, field_kind=field_kind)
    if operator == "in":
        return _normalize_value(resolved, field_kind=field_kind) in [
            _normalize_value(item, field_kind=field_kind)
            for item in (target or [])
        ]
    if operator == "not_in":
        return _normalize_value(resolved, field_kind=field_kind) not in [
            _normalize_value(item, field_kind=field_kind)
            for item in (target or [])
        ]
    if operator == "gt":
        return _coerce_number(resolved, field=filter_node.field, operator=operator) > float(target)
    if operator == "gte":
        return _coerce_number(resolved, field=filter_node.field, operator=operator) >= float(target)
    if operator == "lt":
        return _coerce_number(resolved, field=filter_node.field, operator=operator) < float(target)
    if operator == "lte":
        return _coerce_number(resolved, field=filter_node.field, operator=operator) <= float(target)

    raise BadRequestAppException(f"predictions_json filter does not support operator={operator}")


def _resolve_field_value(
    *,
    annotation: Annotation,
    label_name_by_id: Mapping[uuid.UUID, str],
    field: str,
) -> Any:
    if field == "annotation.id":
        return annotation.id
    if field == "annotation.label_id":
        return annotation.label_id
    if field == "annotation.label_name":
        return label_name_by_id.get(annotation.label_id, _MISSING)
    if field == "annotation.type":
        return annotation.type.value if hasattr(annotation.type, "value") else str(annotation.type)
    if field == "annotation.source":
        return annotation.source.value if hasattr(annotation.source, "value") else str(annotation.source)
    if field == "annotation.confidence":
        return annotation.confidence
    if field.startswith("annotation.attrs."):
        return _read_attr_path(annotation.attrs or {}, field[len("annotation.attrs."):])
    raise BadRequestAppException(f"predictions_json filter does not support field={field}")


def _read_attr_path(attrs: Any, path: str) -> Any:
    current = attrs
    for token in [part for part in str(path or "").split(".") if part]:
        if not isinstance(current, Mapping) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _normalize_value(value: Any, *, field_kind: str) -> Any:
    if field_kind == "uuid":
        return str(value)
    if field_kind == "number":
        return float(value)
    if field_kind == "string":
        return str(value)
    return value


def _coerce_number(value: Any, *, field: str, operator: str) -> float:
    if not _is_number(value):
        raise BadRequestAppException(
            f"predictions_json filter field={field} operator={operator} requires numeric field value"
        )
    return float(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
