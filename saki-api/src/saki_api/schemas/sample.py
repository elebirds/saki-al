from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

from saki_api.models.l1.sample import SampleBase


class SampleRead(SampleBase):
    """
    Schema for reading a sample.
    """
    id: UUID
    created_at: datetime
    updated_at: datetime
    # Presigned URL for the primary asset (if available)
    # This allows frontend to directly display the primary image without making additional requests
    primary_asset_url: Optional[str] = None


class ProjectSampleRead(SampleRead):
    """
    Sample read schema for project context.

    Adds L2 annotation state for the current branch/commit.
    """
    annotation_count: int = 0
    is_labeled: bool = False
    has_draft: bool = False
    review_state: Literal["unreviewed", "labeled", "empty_confirmed"] = "unreviewed"
