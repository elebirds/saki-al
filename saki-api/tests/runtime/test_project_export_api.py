from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.api.export import (
    ProjectExportChunkRequest,
    ProjectExportResolveRequest,
)
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.project.service.export import ExportService
from saki_api.modules.shared.modeling.enums import (
    AnnotationSource,
    AnnotationType,
    AuthorType,
    CommitSampleReviewState,
    DatasetType,
    TaskType,
)
from saki_api.modules.storage.domain.asset import Asset
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState


@pytest.fixture
async def export_env(tmp_path):
    db_path = tmp_path / "project_export.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def stub_storage_provider(monkeypatch):
    monkeypatch.setattr(
        "saki_api.modules.storage.service.asset.get_storage_provider",
        lambda: object(),
    )


async def _seed_project(
    session: AsyncSession,
    *,
    enabled_annotation_types: list[AnnotationType],
    include_obb_annotation: bool,
    dataset_type: DatasetType = DatasetType.CLASSIC,
) -> dict[str, object]:
    owner = User(email=f"owner-{uuid.uuid4()}@example.com", hashed_password="hashed")
    session.add(owner)
    await session.flush()

    dataset = Dataset(
        name=f"dataset-{uuid.uuid4()}",
        owner_id=owner.id,
        type=dataset_type,
    )
    session.add(dataset)
    await session.flush()

    project = Project(
        name=f"project-{uuid.uuid4()}",
        task_type=TaskType.DETECTION,
        enabled_annotation_types=enabled_annotation_types,
        config={},
    )
    session.add(project)
    await session.flush()

    session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

    label = Label(project_id=project.id, name="car", color="#ff0000")
    session.add(label)
    await session.flush()

    commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={"sample_count": 3, "annotation_count": 3},
        commit_hash=f"hash-{uuid.uuid4().hex}",
    )
    session.add(commit)
    await session.flush()

    session.add(
        Branch(
            project_id=project.id,
            name="master",
            head_commit_id=commit.id,
            is_protected=True,
            description="master",
        )
    )

    sample_ids: list[uuid.UUID] = []
    for index in range(3):
        asset = Asset(
            hash=f"asset-hash-{uuid.uuid4().hex}",
            path=f"assets/{uuid.uuid4().hex}.jpg",
            bucket="bucket",
            original_filename=f"sample-{index + 1}.jpg",
            extension=".jpg",
            mime_type="image/jpeg",
            size=700 + index,
        )
        session.add(asset)
        await session.flush()

        sample = Sample(
            dataset_id=dataset.id,
            name=f"group/sample-{index + 1}.jpg",
            primary_asset_id=asset.id,
            asset_group={},
            meta_info={"width": 100, "height": 80},
        )
        session.add(sample)
        await session.flush()
        sample_ids.append(sample.id)

        annotation_type = AnnotationType.OBB if include_obb_annotation and index == 1 else AnnotationType.RECT
        geometry = (
            {"obb": {"cx": 50, "cy": 40, "width": 30, "height": 20, "angle_deg_ccw": 10}}
            if annotation_type == AnnotationType.OBB
            else {"rect": {"x": 10, "y": 12, "width": 30, "height": 20}}
        )
        annotation = Annotation(
            sample_id=sample.id,
            label_id=label.id,
            project_id=project.id,
            group_id=uuid.uuid4(),
            lineage_id=uuid.uuid4(),
            geometry=geometry,
            source=AnnotationSource.MANUAL,
            type=annotation_type,
            confidence=1.0,
        )
        session.add(annotation)
        await session.flush()

        session.add(
            CommitAnnotationMap(
                commit_id=commit.id,
                sample_id=sample.id,
                annotation_id=annotation.id,
                project_id=project.id,
            )
        )

        if index < 2:
            session.add(
                CommitSampleState(
                    commit_id=commit.id,
                    sample_id=sample.id,
                    project_id=project.id,
                    state=CommitSampleReviewState.LABELED,
                )
            )

    await session.flush()

    return {
        "project_id": project.id,
        "dataset_id": dataset.id,
        "commit_id": commit.id,
        "sample_ids": sample_ids,
    }


@pytest.mark.anyio
async def test_io_capabilities_respect_enabled_annotation_types(export_env):
    session_local = export_env
    async with session_local() as session:
        rect_only = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
        )
        obb_only = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.OBB],
            include_obb_annotation=False,
        )

        service = ExportService(session)
        rect_capability = await service.get_io_capabilities(project_id=rect_only["project_id"])
        obb_capability = await service.get_io_capabilities(project_id=obb_only["project_id"])

        rect_available = {item.id: item.available for item in rect_capability.export_profiles}
        obb_available = {item.id: item.available for item in obb_capability.export_profiles}

        assert rect_available == {
            "coco": True,
            "voc": True,
            "yolo": True,
            "yolo_obb": True,
            "dota": True,
        }
        assert obb_available == {
            "coco": False,
            "voc": False,
            "yolo": False,
            "yolo_obb": True,
            "dota": True,
        }


@pytest.mark.anyio
async def test_io_capabilities_export_profiles_require_full_project_annotation_policy(export_env):
    session_local = export_env
    async with session_local() as session:
        mixed = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT, AnnotationType.OBB],
            include_obb_annotation=False,
        )

        service = ExportService(session)
        capability = await service.get_io_capabilities(project_id=mixed["project_id"])
        export_available = {item.id: item.available for item in capability.export_profiles}
        import_available = {item.id: item.available for item in capability.import_profiles}

        assert export_available == {
            "coco": False,
            "voc": False,
            "yolo": False,
            "yolo_obb": True,
            "dota": True,
        }
        assert import_available == {
            "coco": True,
            "voc": True,
            "yolo": True,
            "yolo_obb": True,
            "dota": True,
        }


@pytest.mark.anyio
async def test_resolve_export_handles_snapshot_compatibility_and_size_block(export_env, monkeypatch):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT, AnnotationType.OBB],
            include_obb_annotation=True,
        )
        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]
        commit_id = seeded["commit_id"]

        service = ExportService(session)

        by_branch_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "branch_head", "branch_name": "master"},
            sample_scope="all",
            format_profile="coco",
            include_assets=False,
            bundle_layout="merged_zip",
        )
        by_branch = await service.resolve_export(project_id=project_id, payload=by_branch_payload)
        assert by_branch.resolved_commit_id == commit_id
        assert by_branch.blocked is True
        assert by_branch.format_compatibility == "incompatible"
        assert by_branch.block_reason == "PROJECT_ANNOTATION_POLICY_INCOMPATIBLE"

        monkeypatch.setattr(settings, "EXPORT_FRONTEND_MAX_TOTAL_BYTES", 1)

        by_commit_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "commit", "commit_id": commit_id},
            sample_scope="all",
            format_profile="yolo_obb",
            include_assets=True,
            bundle_layout="merged_zip",
        )
        by_commit = await service.resolve_export(project_id=project_id, payload=by_commit_payload)
        assert by_commit.resolved_commit_id == commit_id
        assert by_commit.format_compatibility == "ok"
        assert by_commit.estimated_total_asset_bytes > 0
        assert by_commit.blocked is True
        assert by_commit.block_reason == "ASSET_SIZE_EXCEEDED"


@pytest.mark.anyio
async def test_export_chunk_pagination_and_asset_url_toggle(export_env, monkeypatch):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
        )

        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]
        commit_id = seeded["commit_id"]

        service = ExportService(session)

        async def _fake_download_url(asset_id: uuid.UUID, expires_in_hours: int = 1) -> str:
            return f"https://example.test/assets/{asset_id}?exp={expires_in_hours}"

        monkeypatch.setattr(service.asset_service, "get_presigned_download_url", _fake_download_url)

        page_one = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo",
                bundle_layout="merged_zip",
                include_assets=False,
                cursor=None,
                limit=2,
            ),
        )
        assert page_one.sample_count == 2
        assert page_one.next_cursor == 2
        assert any(file.source_type == "text" for file in page_one.files)

        page_two = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo",
                bundle_layout="merged_zip",
                include_assets=False,
                cursor=page_one.next_cursor,
                limit=2,
            ),
        )
        assert page_two.sample_count == 1
        assert page_two.next_cursor is None
        assert any(file.path.endswith("data.yaml") for file in page_two.files)

        assets_page = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo",
                bundle_layout="merged_zip",
                include_assets=True,
                cursor=0,
                limit=1,
            ),
        )
        assert assets_page.sample_count == 1
        assert any(file.source_type == "url" for file in assets_page.files)
        assert any(
            (file.download_url or "").startswith("https://example.test/assets/")
            for file in assets_page.files
            if file.source_type == "url"
        )


@pytest.mark.anyio
async def test_yolo_obb_export_chunk_supports_poly8(export_env):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT, AnnotationType.OBB],
            include_obb_annotation=True,
        )

        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]
        commit_id = seeded["commit_id"]

        service = ExportService(session)

        rbox_page = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo_obb",
                yolo_label_format="obb_rbox",
                bundle_layout="merged_zip",
                include_assets=False,
                cursor=0,
                limit=1,
            ),
        )
        poly8_page = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo_obb",
                yolo_label_format="obb_poly8",
                bundle_layout="merged_zip",
                include_assets=False,
                cursor=0,
                limit=1,
            ),
        )

        rbox_file = next(file for file in rbox_page.files if file.path.endswith(".txt"))
        poly8_file = next(file for file in poly8_page.files if file.path.endswith(".txt"))
        rbox_line = next(line for line in (rbox_file.text_content or "").splitlines() if line.strip())
        poly8_line = next(line for line in (poly8_file.text_content or "").splitlines() if line.strip())

        assert len(rbox_line.split()) == 6
        assert len(poly8_line.split()) == 9


@pytest.mark.anyio
async def test_resolve_export_rejects_invalid_yolo_label_format_combo(export_env):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
        )

        service = ExportService(session)

        with pytest.raises(BadRequestAppException, match="yolo_label_format=obb_poly8"):
            await service.resolve_export(
                project_id=seeded["project_id"],
                payload=ProjectExportResolveRequest(
                    dataset_ids=[seeded["dataset_id"]],
                    snapshot={"type": "branch_head", "branch_name": "master"},
                    sample_scope="all",
                    format_profile="yolo",
                    yolo_label_format="obb_poly8",
                    include_assets=False,
                    bundle_layout="merged_zip",
                ),
            )


@pytest.mark.anyio
async def test_dota_export_chunk_uses_mmrotate_paths(export_env, monkeypatch):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
        )

        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]
        commit_id = seeded["commit_id"]

        service = ExportService(session)

        async def _fake_download_url(asset_id: uuid.UUID, expires_in_hours: int = 1) -> str:
            return f"https://example.test/assets/{asset_id}?exp={expires_in_hours}"

        monkeypatch.setattr(service.asset_service, "get_presigned_download_url", _fake_download_url)

        page = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="dota",
                bundle_layout="merged_zip",
                include_assets=True,
                cursor=0,
                limit=1,
            ),
        )

        assert page.sample_count == 1
        assert any(
            file.source_type == "text" and "/train/labelTxt/" in file.path
            for file in page.files
        )
        assert any(
            file.source_type == "url" and "/train/images/" in file.path
            for file in page.files
        )


@pytest.mark.anyio
async def test_yolo_data_yaml_names_follow_label_sort_order(export_env):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
        )
        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]
        commit_id = seeded["commit_id"]

        labels = list((await session.exec(select(Label).where(Label.project_id == project_id))).all())
        assert len(labels) == 1
        labels[0].sort_order = 2
        session.add(labels[0])
        session.add(
            Label(
                project_id=project_id,
                name="bus",
                color="#00ff00",
                sort_order=1,
            )
        )
        await session.commit()

        service = ExportService(session)
        page = await service.get_export_chunk(
            project_id=project_id,
            payload=ProjectExportChunkRequest(
                resolved_commit_id=commit_id,
                dataset_ids=[dataset_id],
                sample_scope="all",
                format_profile="yolo",
                bundle_layout="merged_zip",
                include_assets=False,
                cursor=0,
                limit=10,
            ),
        )
        assert page.next_cursor is None

        data_yaml = next((file for file in page.files if file.path.endswith("data.yaml")), None)
        assert data_yaml is not None
        yaml_text = data_yaml.text_content or ""
        assert "  0: bus" in yaml_text
        assert "  1: car" in yaml_text


@pytest.mark.anyio
async def test_resolve_export_uses_only_project_enabled_annotation_policy(export_env):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT],
            include_obb_annotation=False,
            dataset_type=DatasetType.FEDO,
        )

        service = ExportService(session)
        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]

        blocked_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "branch_head", "branch_name": "master"},
            sample_scope="all",
            format_profile="coco",
            include_assets=False,
            bundle_layout="merged_zip",
        )
        coco_result = await service.resolve_export(project_id=project_id, payload=blocked_payload)
        assert coco_result.blocked is False
        assert coco_result.format_compatibility == "ok"

        allowed_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "branch_head", "branch_name": "master"},
            sample_scope="all",
            format_profile="yolo_obb",
            include_assets=False,
            bundle_layout="merged_zip",
        )
        allowed_result = await service.resolve_export(project_id=project_id, payload=allowed_payload)
        assert allowed_result.blocked is False
        assert allowed_result.format_compatibility == "ok"


@pytest.mark.anyio
async def test_resolve_export_enforces_project_annotation_policy_for_classic_dataset(export_env):
    session_local = export_env
    async with session_local() as session:
        seeded = await _seed_project(
            session,
            enabled_annotation_types=[AnnotationType.RECT, AnnotationType.OBB],
            include_obb_annotation=False,
            dataset_type=DatasetType.CLASSIC,
        )

        service = ExportService(session)
        project_id = seeded["project_id"]
        dataset_id = seeded["dataset_id"]

        blocked_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "branch_head", "branch_name": "master"},
            sample_scope="all",
            format_profile="coco",
            include_assets=False,
            bundle_layout="merged_zip",
        )
        blocked_result = await service.resolve_export(project_id=project_id, payload=blocked_payload)
        assert blocked_result.blocked is True
        assert blocked_result.block_reason == "PROJECT_ANNOTATION_POLICY_INCOMPATIBLE"
        assert blocked_result.format_compatibility == "incompatible"

        allowed_payload = ProjectExportResolveRequest(
            dataset_ids=[dataset_id],
            snapshot={"type": "branch_head", "branch_name": "master"},
            sample_scope="all",
            format_profile="yolo_obb",
            include_assets=False,
            bundle_layout="merged_zip",
        )
        allowed_result = await service.resolve_export(project_id=project_id, payload=allowed_payload)
        assert allowed_result.blocked is False
        assert allowed_result.format_compatibility == "ok"
