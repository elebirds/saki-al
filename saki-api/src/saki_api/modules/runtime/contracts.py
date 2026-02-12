"""Runtime module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class BranchSnapshotDTO:
    id: uuid.UUID
    project_id: uuid.UUID
    head_commit_id: uuid.UUID | None
    name: str


class BranchReadContract(Protocol):
    async def get_branch_snapshot(self, branch_id: uuid.UUID) -> BranchSnapshotDTO | None:
        """Read branch snapshot used by runtime orchestration."""
