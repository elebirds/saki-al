"""Project-level annotation type policy matrix.

This module is the single source of truth for:
- Which task types are currently supported for project creation
- Which annotation types are allowed per task type
- Which dataset types impose required annotation types
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.shared.modeling.enums import AnnotationType, DatasetType, TaskType

SUPPORTED_TASK_TYPES: set[TaskType] = {TaskType.DETECTION}

TASK_ALLOWED_ANNOTATION_TYPES: dict[TaskType, tuple[AnnotationType, ...]] = {
    TaskType.DETECTION: (AnnotationType.RECT, AnnotationType.OBB),
}

TASK_DEFAULT_ANNOTATION_TYPES: dict[TaskType, tuple[AnnotationType, ...]] = {
    TaskType.DETECTION: (AnnotationType.RECT, AnnotationType.OBB),
}

DATASET_REQUIRED_ANNOTATION_TYPES: dict[DatasetType, tuple[AnnotationType, ...]] = {
    DatasetType.CLASSIC: (),
    DatasetType.FEDO: (AnnotationType.OBB,),
}


def normalize_enabled_annotation_types(values: Iterable[Any]) -> list[AnnotationType]:
    """Normalize enabled annotation type list and deduplicate while keeping order."""

    normalized: list[AnnotationType] = []
    seen: set[AnnotationType] = set()
    for value in values:
        try:
            ann_type = value if isinstance(value, AnnotationType) else AnnotationType(str(value).strip().lower())
        except ValueError as exc:
            raise BadRequestAppException(f"unsupported annotation type: {value}") from exc
        if ann_type not in seen:
            seen.add(ann_type)
            normalized.append(ann_type)
    return normalized


def _normalize_task_type(task_type: Any) -> TaskType:
    try:
        return task_type if isinstance(task_type, TaskType) else TaskType(str(task_type).strip().lower())
    except ValueError as exc:
        raise BadRequestAppException(f"task_type not supported: {task_type}") from exc


def _normalize_dataset_type(dataset_type: Any) -> DatasetType:
    try:
        return dataset_type if isinstance(dataset_type, DatasetType) else DatasetType(str(dataset_type).strip().lower())
    except ValueError as exc:
        raise BadRequestAppException(f"dataset type not supported: {dataset_type}") from exc


def validate_project_creation_policy(
    *,
    task_type: Any,
    enabled_types: Iterable[Any],
    dataset_types: Iterable[Any],
) -> list[AnnotationType]:
    """Validate project policy at creation time.

    Returns normalized enabled annotation types.
    """

    normalized_task = _normalize_task_type(task_type)
    if normalized_task not in SUPPORTED_TASK_TYPES:
        raise BadRequestAppException(f"task_type not supported: {normalized_task.value}")

    normalized_enabled = normalize_enabled_annotation_types(enabled_types)
    if not normalized_enabled:
        raise BadRequestAppException("enabled_annotation_types must contain at least one type")

    allowed = set(TASK_ALLOWED_ANNOTATION_TYPES.get(normalized_task, ()))
    unknown = [item.value for item in normalized_enabled if item not in allowed]
    if unknown:
        raise BadRequestAppException(
            f"task_type {normalized_task.value} does not allow annotation type(s): {', '.join(unknown)}"
        )

    for dataset_type in dataset_types:
        validate_dataset_link_compatibility(
            project_enabled_types=normalized_enabled,
            dataset_type=dataset_type,
        )

    return normalized_enabled


def validate_dataset_link_compatibility(
    *,
    project_enabled_types: Iterable[Any],
    dataset_type: Any,
) -> None:
    """Validate whether a dataset type can be linked with current enabled types."""

    normalized_dataset = _normalize_dataset_type(dataset_type)
    normalized_enabled = normalize_enabled_annotation_types(project_enabled_types)
    enabled_set = set(normalized_enabled)
    required = DATASET_REQUIRED_ANNOTATION_TYPES.get(normalized_dataset, ())
    missing = [item.value for item in required if item not in enabled_set]
    if missing:
        raise BadRequestAppException(
            f"dataset type {normalized_dataset.value} requires {', '.join(missing)} enabled"
        )


def assert_annotation_type_enabled(
    *,
    project_enabled_types: Iterable[Any],
    ann_type: Any,
) -> None:
    """Ensure annotation type is enabled by project policy."""

    enabled = set(normalize_enabled_annotation_types(project_enabled_types))
    try:
        normalized = ann_type if isinstance(ann_type, AnnotationType) else AnnotationType(str(ann_type).strip().lower())
    except ValueError as exc:
        raise BadRequestAppException(f"unsupported annotation type: {ann_type}") from exc

    if normalized not in enabled:
        raise BadRequestAppException(f"annotation type {normalized.value} is not enabled for this project")

