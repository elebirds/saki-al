from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from saki_api.modules.project.api.http import project as project_endpoint
from saki_api.modules.storage.domain.sample import Sample


@dataclass
class _FakeProjectSamplePage:
    samples: list[Sample]
    total: int
    offset: int
    limit: int
    annotation_counts: dict[uuid.UUID, int]
    drafts_by_sample: set[uuid.UUID]
    review_states: dict[uuid.UUID, object]


class _FakeProjectService:
    def __init__(self, page: _FakeProjectSamplePage) -> None:
        self._page = page

    async def list_project_samples_page(self, **kwargs):
        del kwargs
        return self._page


class _FailingAssetService:
    async def get_presigned_download_url(self, asset_id):
        del asset_id
        raise RuntimeError("storage unavailable")


class _LoggerProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def warning(self, message: str, *args: object) -> None:
        self.calls.append((message, args))


@pytest.mark.anyio
async def test_list_project_samples_logs_warning_when_primary_asset_url_generation_fails(monkeypatch):
    dataset_id = uuid.uuid4()
    sample = Sample(
        dataset_id=dataset_id,
        name="sample-1.jpg",
        primary_asset_id=uuid.uuid4(),
        asset_group={},
        meta_info={},
    )
    page = _FakeProjectSamplePage(
        samples=[sample],
        total=1,
        offset=0,
        limit=24,
        annotation_counts={sample.id: 0},
        drafts_by_sample=set(),
        review_states={},
    )
    logger_probe = _LoggerProbe()
    monkeypatch.setattr(project_endpoint, "logger", logger_probe)

    response = await project_endpoint.list_project_samples(
        project_id=uuid.uuid4(),
        dataset_id=dataset_id,
        project_service=_FakeProjectService(page),
        asset_service=_FailingAssetService(),
        current_user_id=uuid.uuid4(),
        branch_name="master",
        q=None,
        status="all",
        sort_by="createdAt",
        sort_order="desc",
        page=1,
        limit=24,
    )

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].id == sample.id
    assert response.items[0].primary_asset_url is None
    assert len(logger_probe.calls) == 1
