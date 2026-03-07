"""
CommitSampleState model for per-commit sample review status.
"""

import uuid

from sqlmodel import Field, SQLModel, Index

from saki_api.modules.shared.modeling.enums import CommitSampleReviewState


class CommitSampleState(SQLModel, table=True):
    __tablename__ = "commit_sample_state"

    commit_id: uuid.UUID = Field(primary_key=True, foreign_key="commit.id", index=True)
    sample_id: uuid.UUID = Field(primary_key=True, foreign_key="sample.id", index=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    state: CommitSampleReviewState = Field(index=True)

    __table_args__ = (
        Index("idx_commit_sample_state_lookup", "commit_id", "sample_id", "state"),
    )
