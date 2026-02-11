"""
Project Schemas for API requests and responses.
"""

import uuid
from typing import Any

from sqlmodel import SQLModel

from saki_api.models.enums import TaskType, ProjectStatus


class ProjectBase(SQLModel):
    """
    Base project fields shared across schemas.
    """
    name: str
    description: str | None = None
    task_type: TaskType = TaskType.DETECTION
    status: ProjectStatus = ProjectStatus.ACTIVE
    config: dict[str, Any] = {}


class ProjectCreate(SQLModel):
    """
    Schema for creating a project.
    """
    name: str
    description: str | None = None
    task_type: TaskType = TaskType.DETECTION
    config: dict[str, Any] = {}
    dataset_ids: list[uuid.UUID] = []  # Datasets to link on creation


class ProjectUpdate(SQLModel):
    """
    Schema for updating a project.
    """
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
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
    status: ProjectStatus
