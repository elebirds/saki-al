from __future__ import annotations

import uuid

import pytest
from google.protobuf import struct_pb2
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.grpc_gen import runtime_domain_pb2 as domain_pb
from saki_api.infra.grpc import runtime_control
from saki_api.modules.access.domain.access.user import User
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.dataset_snapshot import DatasetSnapshotSampleOrdinal
from saki_api.modules.runtime.domain.dataset_view import ALSessionState
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    LoopMode,
    LoopPhase,
    LoopStatus,
    RoundStatus,
    TaskType,
)
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample


class _DummyContext:
    def __init__(self) -> None:
        self.code = None
        self.details = ""

    def set_code(self, code) -> None:  # noqa: ANN001
        self.code = code

    def set_details(self, details: str) -> None:
        self.details = details


def _plan_struct(**kwargs) -> struct_pb2.Struct:
    payload = struct_pb2.Struct()
    payload.update(kwargs)
    return payload


@pytest.fixture
async def runtime_domain_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_domain_dataset_manifest.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(runtime_control, "SessionLocal", session_local)
    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_dataset(session: AsyncSession, *, sample_count: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    user = User(email=f"owner-{uuid.uuid4()}@example.com", hashed_password="hashed")
    session.add(user)
    await session.flush()

    dataset = Dataset(name="dataset-runtime-domain", owner_id=user.id)
    session.add(dataset)
    await session.flush()

    sample_ids = [uuid.UUID(int=index + 1) for index in range(sample_count)]
    for index, sample_id in enumerate(sample_ids):
        session.add(
            Sample(
                id=sample_id,
                dataset_id=dataset.id,
                name=f"sample-{index:04d}",
                asset_group={},
            )
        )
    await session.commit()
    return dataset.id, sample_ids


async def _seed_loop_rounds(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    project = Project(name="runtime-domain-project", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    head_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
        extra={},
        commit_hash="init",
    )
    session.add(head_commit)
    await session.flush()

    branch = Branch(
        project_id=project.id,
        name="master",
        head_commit_id=head_commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.flush()

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="loop-1",
        mode=LoopMode.ACTIVE_LEARNING,
        phase=LoopPhase.AL_BOOTSTRAP,
        model_arch="yolo",
        config={},
        status=LoopStatus.RUNNING,
    )
    session.add(loop)
    await session.flush()

    round_1 = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        mode=LoopMode.ACTIVE_LEARNING,
        state=RoundStatus.RUNNING,
    )
    round_2 = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=2,
        mode=LoopMode.ACTIVE_LEARNING,
        state=RoundStatus.RUNNING,
    )
    session.add(round_1)
    session.add(round_2)
    await session.commit()
    return loop.id, round_1.id, round_2.id


def _decode_manifest_ordinals(manifest: domain_pb.DatasetManifestRef) -> set[int]:
    return set(
        runtime_control._decode_selector_bytes(  # noqa: SLF001
            int(manifest.selector.encoding),
            bytes(manifest.selector.selector_bytes),
        )
    )


@pytest.mark.anyio
async def test_build_dataset_snapshot_keeps_ordinal_tombstone_and_append_only(runtime_domain_env):
    session_local = runtime_domain_env
    async with session_local() as session:
        dataset_id, sample_ids = await _seed_dataset(session, sample_count=3)

    service = runtime_control.RuntimeDomainService()
    context = _DummyContext()

    first = await service.BuildDatasetSnapshot(
        domain_pb.BuildDatasetSnapshotRequest(
            dataset_id=str(dataset_id),
            tombstone_sample_uuids=[str(sample_ids[1])],
        ),
        context,
    )
    assert first.created is True

    extra_a = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    second = await service.BuildDatasetSnapshot(
        domain_pb.BuildDatasetSnapshotRequest(
            dataset_id=str(dataset_id),
            parent_snapshot_id=first.snapshot_id,
            append_sample_uuids=[str(extra_a)],
        ),
        context,
    )
    assert second.created is True

    extra_b = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    third = await service.BuildDatasetSnapshot(
        domain_pb.BuildDatasetSnapshotRequest(
            dataset_id=str(dataset_id),
            parent_snapshot_id=second.snapshot_id,
            tombstone_sample_uuids=[str(extra_a)],
            append_sample_uuids=[str(extra_b)],
        ),
        context,
    )
    assert third.created is True
    assert third.max_ordinal == 4
    assert third.universe_size == 5

    async with session_local() as session:
        rows = list(
            (
                await session.exec(
                    select(DatasetSnapshotSampleOrdinal)
                    .where(DatasetSnapshotSampleOrdinal.snapshot_id == uuid.UUID(third.snapshot_id))
                    .order_by(DatasetSnapshotSampleOrdinal.ordinal.asc())
                )
            ).all()
        )

    assert [int(item.ordinal) for item in rows] == [0, 1, 2, 3, 4]
    by_sample = {item.sample_uuid: item for item in rows}
    assert by_sample[extra_a].ordinal == 3
    assert by_sample[extra_a].is_tombstone is True
    assert by_sample[extra_b].ordinal == 4
    assert by_sample[extra_b].is_tombstone is False


@pytest.mark.anyio
async def test_create_round_dataset_view_keeps_static_splits_and_updates_train(runtime_domain_env):
    session_local = runtime_domain_env
    async with session_local() as session:
        dataset_id, _ = await _seed_dataset(session, sample_count=40)
        loop_id, round_1_id, round_2_id = await _seed_loop_rounds(session)

    service = runtime_control.RuntimeDomainService()
    context = _DummyContext()

    snapshot = await service.BuildDatasetSnapshot(
        domain_pb.BuildDatasetSnapshotRequest(dataset_id=str(dataset_id)),
        context,
    )
    assert snapshot.created is True

    plan = _plan_struct(
        seed=7,
        val_rate=0.15,
        test_rate=0.15,
        min_val=2,
        min_test=2,
        initial_train_rate=0.2,
        initial_train_min=2,
        simulation_growth_rate=0.3,
        simulation_growth_min_count=1,
    )
    first_view = await service.CreateRoundDatasetView(
        domain_pb.CreateRoundDatasetViewRequest(
            loop_id=str(loop_id),
            round_id=str(round_1_id),
            snapshot_id=snapshot.snapshot_id,
            round_index=1,
            mode="ACTIVE_LEARNING",
            simulation_mode=False,
            plan=plan,
        ),
        context,
    )
    second_view = await service.CreateRoundDatasetView(
        domain_pb.CreateRoundDatasetViewRequest(
            loop_id=str(loop_id),
            round_id=str(round_2_id),
            snapshot_id=snapshot.snapshot_id,
            round_index=2,
            mode="ACTIVE_LEARNING",
            simulation_mode=True,
            plan=plan,
        ),
        context,
    )

    first_by_split = {item.split: item for item in first_view.manifests}
    second_by_split = {item.split: item for item in second_view.manifests}
    assert set(first_by_split.keys()) == {"train", "unlabeled", "val", "test"}
    assert set(second_by_split.keys()) == {"train", "unlabeled", "val", "test"}
    assert first_by_split["val"].is_static is True
    assert first_by_split["test"].is_static is True
    assert second_by_split["val"].is_static is True
    assert second_by_split["test"].is_static is True

    assert _decode_manifest_ordinals(first_by_split["val"]) == _decode_manifest_ordinals(second_by_split["val"])
    assert _decode_manifest_ordinals(first_by_split["test"]) == _decode_manifest_ordinals(second_by_split["test"])
    assert int(second_by_split["train"].selector.cardinality) > int(first_by_split["train"].selector.cardinality)
    assert int(second_by_split["unlabeled"].selector.cardinality) < int(first_by_split["unlabeled"].selector.cardinality)

    async with session_local() as session:
        state = (await session.exec(select(ALSessionState).where(ALSessionState.loop_id == loop_id))).first()
    assert state is not None
    assert state.round_id == round_2_id
    assert state.round_index == 2
    assert str(state.snapshot_id) == snapshot.snapshot_id


@pytest.mark.anyio
async def test_validate_selector_reports_cardinality_and_checksum():
    service = runtime_control.RuntimeDomainService()
    context = _DummyContext()
    snapshot_id = str(uuid.uuid4())
    selector_bytes = b"\x0d"  # bits 0,2,3

    expected_cardinality, expected_checksum = runtime_control._compute_selector_cardinality_and_checksum(  # noqa: SLF001
        snapshot_id=snapshot_id,
        encoding=domain_pb.SELECTOR_ENCODING_BITSET,
        selector_bytes=selector_bytes,
    )

    bad = await service.ValidateSelector(
        domain_pb.ValidateSelectorRequest(
            selector=domain_pb.SelectorDigest(
                snapshot_id=snapshot_id,
                encoding=domain_pb.SELECTOR_ENCODING_BITSET,
                selector_bytes=selector_bytes,
                cardinality=1,
            )
        ),
        context,
    )
    assert bad.ok is False
    assert "cardinality mismatch" in bad.reason

    good = await service.ValidateSelector(
        domain_pb.ValidateSelectorRequest(
            selector=domain_pb.SelectorDigest(
                snapshot_id=snapshot_id,
                encoding=domain_pb.SELECTOR_ENCODING_BITSET,
                selector_bytes=selector_bytes,
                cardinality=expected_cardinality,
                checksum=expected_checksum,
            )
        ),
        context,
    )
    assert good.ok is True
    assert good.cardinality == expected_cardinality
    assert good.checksum == expected_checksum
