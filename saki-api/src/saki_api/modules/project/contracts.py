"""Project module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.project.api.branch import BranchCreate
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project
from saki_api.modules.project.repo import ProjectRepository
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.project.repo.commit import CommitRepository
from saki_api.modules.project.repo.dataset import DatasetRepository
from saki_api.modules.project.repo.label import LabelRepository
from saki_api.modules.project.repo.sample import SampleRepository
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


@dataclass(slots=True)
class ProjectSnapshotDTO:
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str


class ProjectReadContract(Protocol):
    async def get_project_snapshot(self, project_id: uuid.UUID) -> ProjectSnapshotDTO | None:
        """Read project snapshot for cross-module orchestration."""


class ProjectReadGateway(ProjectReadContract):
    """Cross-module read facade for project-owned data."""

    def __init__(self, session: AsyncSession) -> None:
        self.project_repo = ProjectRepository(session)
        self.branch_repo = BranchRepository(session)
        self.commit_repo = CommitRepository(session)
        self.label_repo = LabelRepository(session)
        self.sample_repo = SampleRepository(session)
        self.dataset_repo = DatasetRepository(session)

    async def get_project_snapshot(self, project_id: uuid.UUID) -> ProjectSnapshotDTO | None:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            return None
        return ProjectSnapshotDTO(id=project.id, owner_id=project.owner_id, name=project.name)

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        return await self.project_repo.get_by_id(project_id)

    async def get_branch(self, branch_id: uuid.UUID) -> Branch | None:
        return await self.branch_repo.get_by_id(branch_id)

    async def get_branch_head_commit_id(self, branch_id: uuid.UUID) -> uuid.UUID | None:
        return await self.branch_repo.get_head_commit_id(branch_id)

    async def get_branch_name(self, branch_id: uuid.UUID) -> str | None:
        return await self.branch_repo.get_name_by_id(branch_id)

    async def get_branch_in_project(self, *, branch_id: uuid.UUID, project_id: uuid.UUID) -> Branch | None:
        return await self.branch_repo.get_in_project(branch_id=branch_id, project_id=project_id)

    async def get_branch_by_name(self, project_id: uuid.UUID, name: str) -> Branch | None:
        return await self.branch_repo.get_by_name(project_id=project_id, name=name)

    async def create_branch(self, payload: BranchCreate) -> Branch:
        return await self.branch_repo.create(payload.model_dump())

    async def get_commit(self, commit_id: uuid.UUID) -> Commit | None:
        return await self.commit_repo.get_by_id(commit_id)

    async def get_label(self, label_id: uuid.UUID) -> Label | None:
        return await self.label_repo.get_by_id(label_id)

    async def get_sample(self, sample_id: uuid.UUID) -> Sample | None:
        return await self.sample_repo.get_by_id(sample_id)

    async def get_dataset(self, dataset_id: uuid.UUID) -> Dataset | None:
        return await self.dataset_repo.get_by_id(dataset_id)

    async def get_linked_dataset_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        return await self.project_repo.get_linked_dataset_ids(project_id)

    async def list_project_sample_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        return await self.sample_repo.list_ids_by_project(project_id)

    async def is_dataset_owner(self, dataset_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return await self.dataset_repo.is_owner(dataset_id, user_id)
