"""
Label model for annotation labels.
Labels belong to projects and are referenced by Annotations.
"""
import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, Relationship

from saki_api.modules.shared.modeling.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.modules.project.domain.project import Project
    from saki_api.modules.annotation.domain.annotation import Annotation


class LabelBase(SQLModel):
    """
    Base model for Label.
    A Label represents a category/class for annotation within a project.
    """
    name: str = Field(description="Name of the label (e.g., 'Object', 'Background').")
    color: str = Field(default="#1890ff", description="Color code for the label (hex format).")
    description: str | None = Field(default=None, description="Optional description of the label.")

    # UI 增强字段
    sort_order: int = Field(default=0, description="在界面上的排列顺序。")
    shortcut: str | None = Field(default=None, max_length=10, description="前端标注快捷键 (e.g., 'q', '1').")


class Label(LabelBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Label.
    Labels are defined per-project and referenced by annotations.
    """
    # Foreign key to project
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True,
                                  description="ID of the project this label belongs to.")

    # Relationships
    project: "Project" = Relationship(back_populates="labels")
    annotations: List["Annotation"] = Relationship(back_populates="label")

    __tablename__ = "label"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_label_name"),
    )
