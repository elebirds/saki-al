"""
Commit model for git-like version control system.
Represents a snapshot of the annotations at a specific point in time.
---
提交 Commit 模型，用于实现类似 Git 的版本控制系统。
表示在特定时间点对标注数据的快照。

Commit 提交时机：
1. 初始提交 (Init)：创建项目时产生，parent_id 为空，author_type = SYSTEM。
2. 人工提交 (Save)：用户在 Web 界面点击“保存”，产生新 Commit，author_type = USER，author_id 指向该用户id。
3. AI 提交 (Inference)：主动学习脚本跑完预标注，产生新 Commit，author_type = MODEL，author_id 指向该训练任务。
"""
import uuid
from typing import Dict, Any, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import AuthorType

if TYPE_CHECKING:
    from saki_api.models.l2.project import Project


class CommitBase(SQLModel):
    """
    Base model for Commit.
    Represents a snapshot of the annotations at a specific point in time.
    """
    # 业务归属字段
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True,
                                  description="ID of the project this commit belongs to.")

    # Git-like 版本控制字段
    parent_id: uuid.UUID | None = Field(default=None, foreign_key="commit.id", index=True,
                                        description="ID of the parent commit (forms version tree).")

    # 审计字段
    message: str = Field(max_length=500, description="Commit message describing this version.")
    author_type: AuthorType = Field(default=AuthorType.USER, index=True,
                                    description="Type of the author who created this commit (USER, MODEL, SYSTEM).")
    author_id: uuid.UUID | None = Field(default=None, description="ID of the user/model who created this commit.")

    # 统计信息（冗余存储）
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="Commit statistics (annotation count, sample count, etc.)."
    )

    # 扩展信息
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="Additional commit metadata."
    )

    # Stable logical hash for commit identity across forks/clones.
    commit_hash: str = Field(
        default="",
        max_length=64,
        index=True,
        description="Stable SHA256 commit hash derived from parent hash + metadata + snapshot content."
    )


class Commit(CommitBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Commit.
    Immutable snapshot of dataset state.
    """
    __tablename__ = "commit"

    project: "Project" = Relationship(back_populates="commits")
