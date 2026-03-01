"""
Project Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.enums import AnnotationType, TaskType, ProjectStatus, DatasetType


class ProjectBase(SQLModel):
    """
    Base project fields shared across schemas.
    """
    name: str
    description: str | None = None
    task_type: TaskType = TaskType.DETECTION
    dataset_type: DatasetType = DatasetType.CLASSIC
    enabled_annotation_types: list[AnnotationType] = Field(
        default_factory=lambda: [AnnotationType.RECT, AnnotationType.OBB]
    )
    status: ProjectStatus = ProjectStatus.ACTIVE
    config: dict[str, Any] = Field(default_factory=dict)


class ProjectCreate(SQLModel):
    """
    Schema for creating a project.
    """
    name: str
    description: str | None = None
    task_type: TaskType = TaskType.DETECTION
    dataset_type: DatasetType = DatasetType.CLASSIC
    enabled_annotation_types: list[AnnotationType]
    config: dict[str, Any] = Field(default_factory=dict)
    dataset_ids: list[uuid.UUID] = Field(default_factory=list)  # Datasets to link on creation


class ProjectForkCreate(SQLModel):
    """
    Schema for forking an existing project.
    """
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None


class ProjectUpdate(SQLModel):
    """
    Schema for updating a project.
    """
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class ProjectRead(ProjectBase):
    """
    Schema for reading a project.
    """
    id: uuid.UUID
    created_at: Any
    updated_at: Any

    # Aggregated counts (optional, can be populated by service)
    dataset_count: int = 0
    label_count: int = 0
    branch_count: int = 0
    commit_count: int = 0
    annotation_count: int = 0
    fork_count: int = 0


class ProjectDatasetLink(SQLModel):
    """
    Schema for linking/unlinking datasets to/from a project.
    """
    dataset_ids: list[uuid.UUID]


class ProjectReadMinimal(SQLModel):
    """
    Minimal project schema for dropdowns/selection.
    """
    id: uuid.UUID
    name: str
    task_type: TaskType
    dataset_type: DatasetType
    status: ProjectStatus
