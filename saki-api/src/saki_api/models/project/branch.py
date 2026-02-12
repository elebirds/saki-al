"""
Branch model for version control.
Branches act as pointers to the current HEAD commit in a project.
---
分支 Branch 模型，用于版本控制。
分支作为项目中当前 HEAD 提交的指针。
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from saki_api.models.project.commit import Commit
    from saki_api.models.project.project import Project
    from saki_api.models.runtime.loop import ALLoop


class BranchBase(SQLModel):
    """
    Base model for Branch.
    Acts as a pointer to the current HEAD commit.
    """
    name: str = Field(index=True, max_length=100, description="Branch name (e.g., 'master', 'al-iter-1').")
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True,
                                  description="ID of the project this branch belongs to.")
    head_commit_id: uuid.UUID = Field(foreign_key="commit.id", description="ID of the latest commit on this branch.")
    description: str | None = Field(default=None, max_length=500, description="Description of this branch.")
    is_protected: bool = Field(default=False, description="Whether this branch is protected from deletion.")


class Branch(BranchBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Branch.
    """
    __tablename__ = "branch"

    # Unique constraint: project can't have duplicate branch names
    __table_args__ = (
        UniqueConstraint('project_id', 'name', name='uq_project_branch_name'),
    )

    project: "Project" = Relationship(back_populates="branches")
    head_commit: "Commit" = Relationship()
    # 允许反向找到它所属的 Loop（如果是实验分支的话）
    active_learning_loop: Optional["ALLoop"] = Relationship(
        back_populates="branch",
        sa_relationship_kwargs={"uselist": False}
    )
