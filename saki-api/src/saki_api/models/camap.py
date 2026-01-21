"""
CommitAnnotationMap models for mapping commits, samples, and annotations.
---
版本-样本-标注映射表，L2 层核心模型。
这是系统的“索引中枢”，决定了在某个版本下，哪些标注是可见的。
"""
import uuid

from sqlmodel import Field, SQLModel, Index


class CommitAnnotationMap(SQLModel, table=True):
    __tablename__ = "commit_annotation_map"

    # 复合主键：这三个字段共同决定唯一性
    commit_id: uuid.UUID = Field(primary_key=True, foreign_key="commit.id", index=True)
    sample_id: uuid.UUID = Field(primary_key=True, foreign_key="sample.id", index=True)
    annotation_id: uuid.UUID = Field(primary_key=True, foreign_key="annotation.id", index=True)
    
    # 业务归属冗余
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)

    # 额外索引
    __table_args__ = (
        # 覆盖索引：当查询某个 Commit 下所有 Sample 的标注 ID 时，索引直接返回结果，无需回表
        Index("idx_commit_sample_lookup", "commit_id", "sample_id", "annotation_id"),
    )