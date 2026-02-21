"""Runtime-domain gRPC server used by dispatcher."""

from __future__ import annotations

import hashlib
import random
import struct
import uuid
from datetime import UTC, datetime

import grpc
from google.protobuf.json_format import MessageToDict
from loguru import logger
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_domain_pb2 as domain_pb
from saki_api.grpc_gen import runtime_domain_pb2_grpc as domain_pb_grpc
from saki_api.infra.db.session import SessionLocal
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.repo.camap import CAMapRepository
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.repo.branch import BranchRepository
from saki_api.modules.project.repo.commit import CommitRepository
from saki_api.modules.project.repo.commit_sample_state import CommitSampleStateRepository
from saki_api.modules.project.service.commit_hash import refresh_commit_hash
from saki_api.modules.runtime.domain.dataset_snapshot import DatasetSnapshot, DatasetSnapshotSampleOrdinal
from saki_api.modules.runtime.domain.dataset_view import ALSessionState, RoundDatasetView
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.shared.modeling.enums import AuthorType, CommitSampleReviewState, StepType
from saki_api.modules.storage.domain.sample import Sample


def _parse_uuid(raw: str) -> uuid.UUID | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except Exception:
        return None


def _resolve_step_id(step_id: str) -> str:
    return str(step_id or "").strip()


def _build_activation_key(loop_id: uuid.UUID, round_index: int, sample_ids: list[uuid.UUID]) -> str:
    unique_sorted_ids = sorted({str(sample_id) for sample_id in sample_ids if sample_id})
    digest = hashlib.sha256(",".join(unique_sorted_ids).encode("utf-8")).hexdigest()
    return f"{loop_id}:{int(round_index)}:{digest}"


def _to_domain_data_response(response: pb.DataResponse) -> domain_pb.DataResponse:
    step_id = _resolve_step_id(response.step_id)
    return domain_pb.DataResponse(
        request_id=str(response.request_id or ""),
        reply_to=str(response.reply_to or ""),
        step_id=step_id,
        query_type=int(response.query_type),
        payload_id=str(response.payload_id or ""),
        chunk_index=int(response.chunk_index),
        chunk_count=int(response.chunk_count),
        header_proto=bytes(response.header_proto),
        payload_chunk=bytes(response.payload_chunk),
        payload_total_size=int(response.payload_total_size),
        payload_checksum_crc32c=int(response.payload_checksum_crc32c),
        chunk_checksum_crc32c=int(response.chunk_checksum_crc32c),
        next_cursor=str(response.next_cursor or ""),
        is_last_chunk=bool(response.is_last_chunk),
    )


def _compute_selector_cardinality_and_checksum(
    snapshot_id: str,
    encoding: int,
    selector_bytes: bytes,
) -> tuple[int, str]:
    cardinality = 0
    if encoding == domain_pb.SELECTOR_ENCODING_BITSET:
        cardinality = int(sum(int(byte).bit_count() for byte in selector_bytes))
    elif encoding == domain_pb.SELECTOR_ENCODING_RANGE:
        if len(selector_bytes) % 8 != 0:
            raise ValueError("range selector bytes length must be multiple of 8")
        merged: list[tuple[int, int]] = []
        for idx in range(0, len(selector_bytes), 8):
            start, end = struct.unpack("<II", selector_bytes[idx:idx + 8])
            if end < start:
                raise ValueError("range selector contains end < start")
            if not merged:
                merged.append((start, end))
                continue
            last_start, last_end = merged[-1]
            if start <= last_end + 1:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        cardinality = int(sum((end - start + 1) for start, end in merged))

    base = hashlib.sha256()
    base.update((snapshot_id or "").encode("utf-8"))
    base.update(b"\x00")
    base.update(struct.pack("<I", int(encoding)))
    base.update(bytes(selector_bytes))
    base.update(struct.pack("<I", int(cardinality)))
    return cardinality, base.hexdigest()


def _uuid7() -> uuid.UUID:
    generator = getattr(uuid, "uuid7", None)
    if callable(generator):
        return generator()
    return uuid.uuid4()


def _parse_uuid_list(raw_values: list[str]) -> tuple[list[uuid.UUID], str | None]:
    ordered: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in raw_values:
        item = _parse_uuid(raw)
        if item is None:
            return [], f"invalid uuid value: {raw}"
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered, None


def _selector_encoding_to_name(encoding: int) -> str:
    if encoding == domain_pb.SELECTOR_ENCODING_RANGE:
        return "RANGE"
    if encoding == domain_pb.SELECTOR_ENCODING_ROARING:
        return "ROARING"
    return "BITSET"


def _selector_name_to_encoding(name: str) -> int:
    upper = str(name or "").strip().upper()
    if upper == "RANGE":
        return domain_pb.SELECTOR_ENCODING_RANGE
    if upper == "ROARING":
        return domain_pb.SELECTOR_ENCODING_ROARING
    return domain_pb.SELECTOR_ENCODING_BITSET


def _decode_selector_bytes(encoding: int, selector_bytes: bytes) -> list[int]:
    if encoding == domain_pb.SELECTOR_ENCODING_RANGE:
        if len(selector_bytes) % 8 != 0:
            raise ValueError("range selector bytes length must be multiple of 8")
        values: list[int] = []
        for idx in range(0, len(selector_bytes), 8):
            start, end = struct.unpack("<II", selector_bytes[idx:idx + 8])
            if end < start:
                raise ValueError("range selector contains end < start")
            values.extend(range(int(start), int(end) + 1))
        return values
    if encoding == domain_pb.SELECTOR_ENCODING_BITSET:
        values: list[int] = []
        for byte_idx, byte_value in enumerate(selector_bytes):
            for bit_idx in range(8):
                if (byte_value >> bit_idx) & 1:
                    values.append(byte_idx * 8 + bit_idx)
        return values
    # ROARING 目前只校验 checksum/cardinality，不解码明细。
    return []


def _encode_selector_from_ordinals(snapshot_id: str, ordinals: list[int], universe_size: int) -> tuple[int, bytes, int, str]:
    dedup_sorted = sorted({int(item) for item in ordinals if int(item) >= 0})
    cardinality = len(dedup_sorted)
    if cardinality == 0:
        checksum = _compute_selector_cardinality_and_checksum(snapshot_id, domain_pb.SELECTOR_ENCODING_RANGE, b"")[1]
        return domain_pb.SELECTOR_ENCODING_RANGE, b"", 0, checksum

    ranges: list[tuple[int, int]] = []
    start = dedup_sorted[0]
    end = dedup_sorted[0]
    for value in dedup_sorted[1:]:
        if value == end + 1:
            end = value
            continue
        ranges.append((start, end))
        start = value
        end = value
    ranges.append((start, end))
    range_bytes = b"".join(struct.pack("<II", int(s), int(e)) for s, e in ranges)

    bitset_size = max(int(universe_size), dedup_sorted[-1] + 1, 1)
    bitset = bytearray((bitset_size + 7) // 8)
    for ordinal in dedup_sorted:
        byte_idx = ordinal // 8
        bit_idx = ordinal % 8
        bitset[byte_idx] |= (1 << bit_idx)
    bitset_bytes = bytes(bitset)

    if len(ranges) <= 16 and len(range_bytes) <= len(bitset_bytes):
        encoding = domain_pb.SELECTOR_ENCODING_RANGE
        selector_bytes = range_bytes
    else:
        encoding = domain_pb.SELECTOR_ENCODING_BITSET
        selector_bytes = bitset_bytes
    _, checksum = _compute_selector_cardinality_and_checksum(snapshot_id, encoding, selector_bytes)
    return encoding, selector_bytes, cardinality, checksum


def _split_holdout_counts(total: int, val_rate: float, test_rate: float, min_val: int, min_test: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    if total < 3:
        return min(1, total), max(0, total - 1)

    if total < 300:
        val = max(1, int(round(total * val_rate)))
        test = max(1, int(round(total * test_rate)))
    else:
        val = max(min_val, int(total * val_rate))
        test = max(min_test, int(total * test_rate))

    if val + test >= total:
        overflow = val + test - total + 1
        while overflow > 0 and (val > 1 or test > 1):
            if val >= test and val > 1:
                val -= 1
            elif test > 1:
                test -= 1
            overflow -= 1
    if val + test >= total:
        test = max(1, total - val - 1)
        val = max(1, total - test - 1)
    return max(1, val), max(1, test)


class RuntimeDomainService(domain_pb_grpc.RuntimeDomainServicer):
    def __init__(self) -> None:
        self._storage = None
        self._runtime_ingress = RuntimeControlIngressService(
            session_local=SessionLocal,
            storage_resolver=self._resolve_storage,
        )

    def _resolve_storage(self):
        return self.storage

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def GetBranchHead(self, request, context):  # noqa: N802
        branch_id = _parse_uuid(request.branch_id)
        if branch_id is None:
            return domain_pb.GetBranchHeadResponse(found=False)

        async with SessionLocal() as session:
            branch = await BranchRepository(session).get_by_id(branch_id)
            if not branch:
                return domain_pb.GetBranchHeadResponse(found=False)
            return domain_pb.GetBranchHeadResponse(
                found=True,
                branch_id=str(branch.id),
                project_id=str(branch.project_id),
                branch_name=str(branch.name or ""),
                head_commit_id=str(branch.head_commit_id or ""),
            )

    async def CountNewLabelsSinceCommit(self, request, context):  # noqa: N802
        branch_id = _parse_uuid(request.branch_id)
        since_commit_id = _parse_uuid(request.since_commit_id)
        if branch_id is None:
            return domain_pb.CountNewLabelsSinceCommitResponse(new_label_count=0, latest_commit_id="")

        async with SessionLocal() as session:
            branch = await BranchRepository(session).get_by_id(branch_id)
            if not branch or not branch.head_commit_id:
                return domain_pb.CountNewLabelsSinceCommitResponse(new_label_count=0, latest_commit_id="")

            camap_repo = CAMapRepository(session)
            latest_commit_id = branch.head_commit_id
            latest_count = int(await camap_repo.count_annotations_at_commit(latest_commit_id))
            since_count = 0
            if since_commit_id:
                since_count = int(await camap_repo.count_annotations_at_commit(since_commit_id))

            return domain_pb.CountNewLabelsSinceCommitResponse(
                new_label_count=max(0, latest_count - since_count),
                latest_commit_id=str(latest_commit_id),
            )

    async def _list_snapshot_rows(
            self,
            *,
            session,
            snapshot_id: uuid.UUID,
    ) -> list[DatasetSnapshotSampleOrdinal]:
        statement = (
            select(DatasetSnapshotSampleOrdinal)
            .where(DatasetSnapshotSampleOrdinal.snapshot_id == snapshot_id)
            .order_by(DatasetSnapshotSampleOrdinal.ordinal.asc())
        )
        return list((await session.exec(statement)).all())

    async def _upsert_round_dataset_view(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            round_id: uuid.UUID,
            split: str,
            is_static: bool,
            snapshot_id: uuid.UUID,
            encoding: int,
            selector_bytes: bytes,
            cardinality: int,
            checksum: str,
            manifest_ref: str,
    ) -> RoundDatasetView:
        split_name = str(split or "").strip().lower()
        statement = (
            select(RoundDatasetView)
            .where(
                RoundDatasetView.round_id == round_id,
                RoundDatasetView.split == split_name,
            )
            .limit(1)
        )
        row = (await session.exec(statement)).first()
        if row is None:
            row = RoundDatasetView(
                id=_uuid7(),
                loop_id=loop_id,
                round_id=round_id,
                split=split_name,
                is_static=is_static,
                snapshot_id=snapshot_id,
                selector_encoding=_selector_encoding_to_name(encoding),
                selector_bytes=bytes(selector_bytes),
                selector_cardinality=int(cardinality),
                selector_checksum=str(checksum),
                manifest_ref=str(manifest_ref),
            )
        else:
            row.is_static = bool(is_static)
            row.snapshot_id = snapshot_id
            row.selector_encoding = _selector_encoding_to_name(encoding)
            row.selector_bytes = bytes(selector_bytes)
            row.selector_cardinality = int(cardinality)
            row.selector_checksum = str(checksum)
            row.manifest_ref = str(manifest_ref)
            row.updated_at = datetime.now(UTC)
        session.add(row)
        return row

    async def _load_latest_split_selector(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            split: str,
    ) -> RoundDatasetView | None:
        statement = (
            select(RoundDatasetView)
            .where(
                RoundDatasetView.loop_id == loop_id,
                RoundDatasetView.split == str(split or "").strip().lower(),
            )
            .order_by(RoundDatasetView.created_at.desc())
            .limit(1)
        )
        return (await session.exec(statement)).first()

    async def _upsert_al_session_state(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            round_id: uuid.UUID | None,
            snapshot_id: uuid.UUID,
            round_index: int,
            encoding: int,
            selector_bytes: bytes,
            cardinality: int,
            checksum: str,
            manifest_ref: str,
    ) -> ALSessionState:
        statement = select(ALSessionState).where(ALSessionState.loop_id == loop_id).limit(1)
        row = (await session.exec(statement)).first()
        if row is None:
            row = ALSessionState(
                id=_uuid7(),
                loop_id=loop_id,
                round_id=round_id,
                snapshot_id=snapshot_id,
                selector_encoding=_selector_encoding_to_name(encoding),
                selector_bytes=bytes(selector_bytes),
                selector_cardinality=int(cardinality),
                selector_checksum=str(checksum),
                selector_manifest_ref=str(manifest_ref),
                round_index=int(round_index),
            )
        else:
            row.round_id = round_id
            row.snapshot_id = snapshot_id
            row.selector_encoding = _selector_encoding_to_name(encoding)
            row.selector_bytes = bytes(selector_bytes)
            row.selector_cardinality = int(cardinality)
            row.selector_checksum = str(checksum)
            row.selector_manifest_ref = str(manifest_ref)
            row.round_index = int(round_index)
            row.updated_at = datetime.now(UTC)
        session.add(row)
        return row

    async def BuildDatasetSnapshot(self, request, context):  # noqa: N802
        dataset_id = _parse_uuid(request.dataset_id)
        if dataset_id is None:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("dataset_id is required")
            return domain_pb.BuildDatasetSnapshotResponse(created=False, snapshot_id="", universe_size=0, max_ordinal=0, tombstone_count=0)

        parent_snapshot_id = _parse_uuid(request.parent_snapshot_id)
        append_ids, append_err = _parse_uuid_list(list(request.append_sample_uuids))
        if append_err:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(append_err)
            return domain_pb.BuildDatasetSnapshotResponse(created=False, snapshot_id="", universe_size=0, max_ordinal=0, tombstone_count=0)
        tombstone_ids, tombstone_err = _parse_uuid_list(list(request.tombstone_sample_uuids))
        if tombstone_err:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(tombstone_err)
            return domain_pb.BuildDatasetSnapshotResponse(created=False, snapshot_id="", universe_size=0, max_ordinal=0, tombstone_count=0)
        tombstone_set = set(tombstone_ids)

        async with SessionLocal() as session:
            parent_snapshot: DatasetSnapshot | None = None
            base_rows: list[DatasetSnapshotSampleOrdinal] = []
            if parent_snapshot_id is not None:
                parent_snapshot = await session.get(DatasetSnapshot, parent_snapshot_id)
                if parent_snapshot is None:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details("parent snapshot not found")
                    return domain_pb.BuildDatasetSnapshotResponse(created=False, snapshot_id="", universe_size=0, max_ordinal=0, tombstone_count=0)
                if parent_snapshot.dataset_id != dataset_id:
                    context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                    context.set_details("parent snapshot dataset mismatch")
                    return domain_pb.BuildDatasetSnapshotResponse(created=False, snapshot_id="", universe_size=0, max_ordinal=0, tombstone_count=0)
                base_rows = await self._list_snapshot_rows(session=session, snapshot_id=parent_snapshot.id)

            if not base_rows:
                sample_statement = (
                    select(Sample.id)
                    .where(Sample.dataset_id == dataset_id)
                    .order_by(Sample.id.asc())
                )
                sample_ids = list((await session.exec(sample_statement)).all())
                current_ordinal = 0
                for sample_id in sample_ids:
                    base_rows.append(
                        DatasetSnapshotSampleOrdinal(
                            snapshot_id=uuid.UUID(int=0),
                            sample_uuid=sample_id,
                            ordinal=current_ordinal,
                            is_tombstone=sample_id in tombstone_set,
                            tombstone_at=(datetime.now(UTC) if sample_id in tombstone_set else None),
                            tombstone_reason=("deleted" if sample_id in tombstone_set else None),
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )
                    current_ordinal += 1
            snapshot_id = _uuid7()
            snapshot = DatasetSnapshot(
                id=snapshot_id,
                dataset_id=dataset_id,
                parent_snapshot_id=(parent_snapshot.id if parent_snapshot is not None else None),
                universe_size=0,
                max_ordinal=0,
                created_at=datetime.now(UTC),
            )
            session.add(snapshot)

            current_max = -1
            existing_sample_ids: set[uuid.UUID] = set()
            for row in sorted(base_rows, key=lambda item: int(item.ordinal)):
                is_tombstone = bool(row.is_tombstone) or row.sample_uuid in tombstone_set
                copied = DatasetSnapshotSampleOrdinal(
                    snapshot_id=snapshot_id,
                    sample_uuid=row.sample_uuid,
                    ordinal=int(row.ordinal),
                    is_tombstone=is_tombstone,
                    tombstone_at=(datetime.now(UTC) if is_tombstone else None),
                    tombstone_reason=(row.tombstone_reason or "deleted" if is_tombstone else None),
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(copied)
                existing_sample_ids.add(row.sample_uuid)
                current_max = max(current_max, int(row.ordinal))

            for sample_id in append_ids:
                if sample_id in existing_sample_ids:
                    continue
                current_max += 1
                session.add(
                    DatasetSnapshotSampleOrdinal(
                        snapshot_id=snapshot_id,
                        sample_uuid=sample_id,
                        ordinal=current_max,
                        is_tombstone=False,
                        tombstone_at=None,
                        tombstone_reason=None,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                existing_sample_ids.add(sample_id)

            snapshot.max_ordinal = max(current_max, 0)
            snapshot.universe_size = max(current_max + 1, 0)
            session.add(snapshot)
            await session.commit()

            rows = await self._list_snapshot_rows(session=session, snapshot_id=snapshot_id)
            tombstone_count = sum(1 for item in rows if item.is_tombstone)
            return domain_pb.BuildDatasetSnapshotResponse(
                created=True,
                snapshot_id=str(snapshot_id),
                universe_size=int(snapshot.universe_size),
                max_ordinal=int(snapshot.max_ordinal),
                tombstone_count=int(tombstone_count),
            )

    async def CreateRoundDatasetView(self, request, context):  # noqa: N802
        loop_id = _parse_uuid(request.loop_id)
        round_id = _parse_uuid(request.round_id)
        snapshot_id = _parse_uuid(request.snapshot_id)
        if loop_id is None or round_id is None or snapshot_id is None:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("loop_id/round_id/snapshot_id are required")
            return domain_pb.CreateRoundDatasetViewResponse(created=False, round_id=str(request.round_id or ""), manifests=[])

        plan = MessageToDict(request.plan, preserving_proto_field_name=True) if request.plan and request.plan.ListFields() else {}
        seed = int(plan.get("seed", 42))
        val_rate = float(plan.get("val_rate", 0.15))
        test_rate = float(plan.get("test_rate", 0.15))
        min_val = int(plan.get("min_val", 50))
        min_test = int(plan.get("min_test", 50))
        initial_train_rate = float(plan.get("initial_train_rate", 0.1))
        initial_train_min = int(plan.get("initial_train_min", 200))
        simulation_growth_rate = float(plan.get("simulation_growth_rate", 0.05))
        simulation_growth_min_count = int(plan.get("simulation_growth_min_count", 10))

        mode = str(request.mode or "").strip().upper()
        is_manual = mode == "MANUAL"

        async with SessionLocal() as session:
            snapshot = await session.get(DatasetSnapshot, snapshot_id)
            if snapshot is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("snapshot not found")
                return domain_pb.CreateRoundDatasetViewResponse(created=False, round_id=str(request.round_id or ""), manifests=[])

            rows = await self._list_snapshot_rows(session=session, snapshot_id=snapshot_id)
            available_ordinals = [int(item.ordinal) for item in rows if not item.is_tombstone]
            available_set = set(available_ordinals)

            static_val: set[int] = set()
            static_test: set[int] = set()
            previous_val = await self._load_latest_split_selector(session=session, loop_id=loop_id, split="val")
            previous_test = await self._load_latest_split_selector(session=session, loop_id=loop_id, split="test")
            if previous_val and previous_test and previous_val.snapshot_id == snapshot_id and previous_test.snapshot_id == snapshot_id:
                static_val = set(_decode_selector_bytes(_selector_name_to_encoding(previous_val.selector_encoding), bytes(previous_val.selector_bytes)))
                static_test = set(_decode_selector_bytes(_selector_name_to_encoding(previous_test.selector_encoding), bytes(previous_test.selector_bytes)))
                static_val &= available_set
                static_test &= available_set
                static_test -= static_val
            else:
                shuffled = list(available_ordinals)
                random.Random(seed).shuffle(shuffled)
                val_count, test_count = _split_holdout_counts(len(shuffled), val_rate, test_rate, min_val, min_test)
                static_val = set(shuffled[:val_count])
                static_test = set(shuffled[val_count:val_count + test_count])

            train_pool = sorted(available_set - static_val - static_test)
            train_set: set[int]
            session_state = (await session.exec(select(ALSessionState).where(ALSessionState.loop_id == loop_id).limit(1))).first()
            if is_manual:
                train_set = set(train_pool)
            elif session_state is not None and session_state.snapshot_id == snapshot_id:
                train_set = set(
                    _decode_selector_bytes(
                        _selector_name_to_encoding(session_state.selector_encoding),
                        bytes(session_state.selector_bytes),
                    )
                )
                train_set &= set(train_pool)
            else:
                shuffled_pool = list(train_pool)
                random.Random(seed).shuffle(shuffled_pool)
                initial_count = max(int(len(shuffled_pool) * initial_train_rate), min(initial_train_min, len(shuffled_pool)))
                if len(shuffled_pool) > 0:
                    initial_count = max(1, min(initial_count, len(shuffled_pool)))
                train_set = set(shuffled_pool[:initial_count])

            if request.simulation_mode and not is_manual:
                unlabeled_now = sorted(set(train_pool) - train_set)
                if unlabeled_now:
                    growth_count = max(int(len(train_pool) * simulation_growth_rate), simulation_growth_min_count)
                    growth_count = max(1, min(growth_count, len(unlabeled_now)))
                    random.Random(seed + int(request.round_index or 0)).shuffle(unlabeled_now)
                    train_set.update(unlabeled_now[:growth_count])

            unlabeled_set = set() if is_manual else (set(train_pool) - train_set)

            split_payloads = {
                "train": (train_set, False),
                "unlabeled": (unlabeled_set, False),
                "val": (static_val, True),
                "test": (static_test, True),
            }
            manifests: list[domain_pb.DatasetManifestRef] = []
            for split_name, (ordinal_set, is_static) in split_payloads.items():
                encoding, selector_bytes, cardinality, checksum = _encode_selector_from_ordinals(
                    snapshot_id=str(snapshot_id),
                    ordinals=sorted(ordinal_set),
                    universe_size=int(snapshot.universe_size),
                )
                manifest_ref = f"manifest://loop/{loop_id}/round/{round_id}/{split_name}"
                await self._upsert_round_dataset_view(
                    session=session,
                    loop_id=loop_id,
                    round_id=round_id,
                    split=split_name,
                    is_static=is_static,
                    snapshot_id=snapshot_id,
                    encoding=encoding,
                    selector_bytes=selector_bytes,
                    cardinality=cardinality,
                    checksum=checksum,
                    manifest_ref=manifest_ref,
                )
                manifests.append(
                    domain_pb.DatasetManifestRef(
                        split=split_name,
                        is_static=is_static,
                        snapshot_id=str(snapshot_id),
                        manifest_ref=manifest_ref,
                        selector=domain_pb.SelectorDigest(
                            snapshot_id=str(snapshot_id),
                            encoding=encoding,
                            selector_bytes=selector_bytes,
                            cardinality=cardinality,
                            checksum=checksum,
                        ),
                    )
                )

            train_manifest = next((item for item in manifests if item.split == "train"), None)
            if train_manifest is not None:
                await self._upsert_al_session_state(
                    session=session,
                    loop_id=loop_id,
                    round_id=round_id,
                    snapshot_id=snapshot_id,
                    round_index=int(request.round_index or 0),
                    encoding=int(train_manifest.selector.encoding),
                    selector_bytes=bytes(train_manifest.selector.selector_bytes),
                    cardinality=int(train_manifest.selector.cardinality),
                    checksum=str(train_manifest.selector.checksum),
                    manifest_ref=str(train_manifest.manifest_ref),
                )

            await session.commit()
            return domain_pb.CreateRoundDatasetViewResponse(
                created=True,
                round_id=str(round_id),
                manifests=manifests,
            )

    async def GetRoundManifest(self, request, context):  # noqa: N802
        round_id = _parse_uuid(request.round_id)
        split_name = str(request.split or "").strip().lower()
        if round_id is None or not split_name:
            return domain_pb.GetRoundManifestResponse(found=False)
        async with SessionLocal() as session:
            statement = (
                select(RoundDatasetView)
                .where(
                    RoundDatasetView.round_id == round_id,
                    RoundDatasetView.split == split_name,
                )
                .limit(1)
            )
            row = (await session.exec(statement)).first()
            if row is None:
                return domain_pb.GetRoundManifestResponse(found=False)
            encoding = _selector_name_to_encoding(row.selector_encoding)
            return domain_pb.GetRoundManifestResponse(
                found=True,
                manifest=domain_pb.DatasetManifestRef(
                    split=split_name,
                    is_static=bool(row.is_static),
                    snapshot_id=str(row.snapshot_id),
                    manifest_ref=str(row.manifest_ref),
                    selector=domain_pb.SelectorDigest(
                        snapshot_id=str(row.snapshot_id),
                        encoding=encoding,
                        selector_bytes=bytes(row.selector_bytes),
                        cardinality=int(row.selector_cardinality),
                        checksum=str(row.selector_checksum),
                    ),
                ),
            )

    async def ValidateSelector(self, request, context):  # noqa: N802
        selector = request.selector
        if not selector.snapshot_id:
            return domain_pb.ValidateSelectorResponse(ok=False, cardinality=0, checksum="", reason="snapshot_id is required")
        if selector.encoding == domain_pb.SELECTOR_ENCODING_UNSPECIFIED:
            return domain_pb.ValidateSelectorResponse(ok=False, cardinality=0, checksum="", reason="selector encoding is required")
        try:
            cardinality, checksum = _compute_selector_cardinality_and_checksum(
                snapshot_id=str(selector.snapshot_id or ""),
                encoding=int(selector.encoding),
                selector_bytes=bytes(selector.selector_bytes),
            )
        except ValueError as exc:
            return domain_pb.ValidateSelectorResponse(ok=False, cardinality=0, checksum="", reason=str(exc))

        expected_cardinality = int(selector.cardinality or 0)
        if expected_cardinality > 0 and expected_cardinality != cardinality:
            return domain_pb.ValidateSelectorResponse(
                ok=False,
                cardinality=cardinality,
                checksum=checksum,
                reason=f"cardinality mismatch expected={expected_cardinality} actual={cardinality}",
            )
        expected_checksum = str(selector.checksum or "").strip().lower()
        if expected_checksum and expected_checksum != checksum:
            return domain_pb.ValidateSelectorResponse(
                ok=False,
                cardinality=cardinality,
                checksum=checksum,
                reason=f"checksum mismatch expected={expected_checksum} actual={checksum}",
            )
        return domain_pb.ValidateSelectorResponse(ok=True, cardinality=cardinality, checksum=checksum, reason="")

    async def _create_simulation_commit_tx(
            self,
            *,
            session,
            project_id: uuid.UUID,
            oracle_commit_id: uuid.UUID,
            parent_commit_id: uuid.UUID,
            selected_sample_ids: list[uuid.UUID],
            command_id: str,
            activation_key: str,
            loop_id: str,
            round_index: int,
            query_strategy: str,
            topk: int,
            snapshot_id: str,
            selector_encoding: int,
            selector_cardinality: int,
            selector_checksum: str,
    ) -> Commit:
        commit = Commit(
            project_id=project_id,
            parent_id=parent_commit_id,
            message=(
                f"[sim] loop={loop_id or '-'} round={int(round_index)} "
                f"strategy={query_strategy or '-'} topk={int(topk)}"
            ),
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
            extra={
                "runtime": {
                    "command_id": str(command_id or ""),
                    "activation_key": str(activation_key or ""),
                    "loop_id": str(loop_id or ""),
                    "round_index": int(round_index),
                    "query_strategy": str(query_strategy or ""),
                    "topk": int(topk),
                    "oracle_commit_id": str(oracle_commit_id),
                    "source_commit_id": str(parent_commit_id),
                    "selected_sample_ids": [str(item) for item in selected_sample_ids],
                    "snapshot_id": str(snapshot_id or ""),
                    "selector_encoding": int(selector_encoding),
                    "selector_cardinality": int(selector_cardinality),
                    "selector_checksum": str(selector_checksum or ""),
                }
            },
            commit_hash="",
        )
        session.add(commit)
        await session.flush()

        camap_repo = CAMapRepository(session)
        parent_state = await camap_repo.get_annotations_for_commit(parent_commit_id)
        base_mappings: list[tuple[uuid.UUID, uuid.UUID]] = []
        for sample_id, annotation_ids in parent_state.items():
            for annotation_id in annotation_ids:
                base_mappings.append((sample_id, annotation_id))
        if base_mappings:
            await camap_repo.set_commit_state(
                commit_id=commit.id,
                mappings=base_mappings,
                project_id=project_id,
            )

        sample_state_repo = CommitSampleStateRepository(session)
        await sample_state_repo.copy_commit_state(
            source_commit_id=parent_commit_id,
            target_commit_id=commit.id,
            project_id=project_id,
        )

        existing_by_sample: dict[uuid.UUID, set[uuid.UUID]] = {
            sample_id: set(annotation_ids) for sample_id, annotation_ids in parent_state.items()
        }
        delta_mappings: list[tuple[uuid.UUID, uuid.UUID]] = []
        for sample_id in selected_sample_ids:
            oracle_annotation_ids = await camap_repo.get_sample_annotations(oracle_commit_id, sample_id)
            if not oracle_annotation_ids:
                continue
            existing = existing_by_sample.setdefault(sample_id, set())
            for annotation_id in oracle_annotation_ids:
                if annotation_id in existing:
                    continue
                existing.add(annotation_id)
                delta_mappings.append((sample_id, annotation_id))

        if delta_mappings:
            await camap_repo.set_commit_state(
                commit_id=commit.id,
                mappings=delta_mappings,
                project_id=project_id,
            )

        for sample_id in selected_sample_ids:
            await sample_state_repo.delete_commit_sample_state(
                commit_id=commit.id,
                sample_id=sample_id,
            )
            await sample_state_repo.set_commit_sample_state(
                commit_id=commit.id,
                sample_id=sample_id,
                project_id=project_id,
                state=CommitSampleReviewState.LABELED,
            )

        commit.stats = await camap_repo.get_commit_stats(commit.id)
        await refresh_commit_hash(session, commit)
        session.add(commit)
        return commit

    async def _load_selected_sample_ids(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            round_index: int,
            topk: int,
    ) -> list[uuid.UUID]:
        limit = max(1, int(topk or 1))
        select_stmt = (
            select(StepCandidateItem.sample_id)
            .join(Step, Step.id == StepCandidateItem.step_id)
            .join(Round, Round.id == Step.round_id)
            .where(
                Round.loop_id == loop_id,
                Round.round_index == round_index,
                Step.step_type == StepType.SELECT,
            )
            .order_by(StepCandidateItem.rank.asc(), StepCandidateItem.created_at.asc())
            .limit(limit)
        )
        sample_ids = list((await session.exec(select_stmt)).all())
        if not sample_ids:
            fallback_stmt = (
                select(StepCandidateItem.sample_id)
                .join(Step, Step.id == StepCandidateItem.step_id)
                .join(Round, Round.id == Step.round_id)
                .where(
                    Round.loop_id == loop_id,
                    Round.round_index == round_index,
                    Step.step_type == StepType.SCORE,
                )
                .order_by(StepCandidateItem.rank.asc(), StepCandidateItem.created_at.asc())
                .limit(limit)
            )
            sample_ids = list((await session.exec(fallback_stmt)).all())

        ordered: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for sample_id in sample_ids:
            if sample_id in seen:
                continue
            seen.add(sample_id)
            ordered.append(sample_id)
        return ordered

    async def _find_existing_activation_commit_tx(
            self,
            *,
            session,
            project_id: uuid.UUID,
            activation_key: str,
    ) -> Commit | None:
        activation_key = str(activation_key or "").strip()
        if not activation_key:
            return None
        statement = (
            select(Commit)
            .where(
                Commit.project_id == project_id,
                Commit.author_type == AuthorType.SYSTEM,
            )
            .order_by(Commit.created_at.desc())
            .limit(256)
        )
        candidates = list((await session.exec(statement)).all())
        for item in candidates:
            extra_payload = item.extra if isinstance(item.extra, dict) else {}
            runtime_extra = extra_payload.get("runtime", {})
            if not isinstance(runtime_extra, dict):
                continue
            if str(runtime_extra.get("activation_key") or "").strip() == activation_key:
                return item
        return None

    async def _grow_train_selector_after_activation(
            self,
            *,
            session,
            loop_id: uuid.UUID,
            round_id: uuid.UUID | None,
            round_index: int,
            snapshot_id: uuid.UUID | None,
            selected_sample_ids: list[uuid.UUID],
    ) -> None:
        if snapshot_id is None:
            return
        if not selected_sample_ids:
            return
        state = (await session.exec(select(ALSessionState).where(ALSessionState.loop_id == loop_id).limit(1))).first()
        if state is None or state.snapshot_id != snapshot_id:
            return
        snapshot = await session.get(DatasetSnapshot, snapshot_id)
        if snapshot is None:
            return

        current_train = set(
            _decode_selector_bytes(
                _selector_name_to_encoding(state.selector_encoding),
                bytes(state.selector_bytes),
            )
        )
        ordinal_rows = list(
            (
                await session.exec(
                    select(DatasetSnapshotSampleOrdinal)
                    .where(
                        DatasetSnapshotSampleOrdinal.snapshot_id == snapshot_id,
                        DatasetSnapshotSampleOrdinal.sample_uuid.in_(selected_sample_ids),
                        DatasetSnapshotSampleOrdinal.is_tombstone.is_(False),
                    )
                )
            ).all()
        )
        for item in ordinal_rows:
            current_train.add(int(item.ordinal))
        encoding, selector_bytes, cardinality, checksum = _encode_selector_from_ordinals(
            snapshot_id=str(snapshot_id),
            ordinals=sorted(current_train),
            universe_size=int(snapshot.universe_size),
        )
        await self._upsert_al_session_state(
            session=session,
            loop_id=loop_id,
            round_id=round_id,
            snapshot_id=snapshot_id,
            round_index=round_index,
            encoding=encoding,
            selector_bytes=selector_bytes,
            cardinality=cardinality,
            checksum=checksum,
            manifest_ref=f"manifest://loop/{loop_id}/round/{round_id or 'unknown'}/train",
        )

    async def ActivateSamples(self, request, context):  # noqa: N802
        project_id = _parse_uuid(request.project_id)
        branch_id = _parse_uuid(request.branch_id)
        oracle_commit_id = _parse_uuid(request.oracle_commit_id)
        source_commit_id = _parse_uuid(request.source_commit_id)
        snapshot_uuid = _parse_uuid(request.snapshot_id)

        if project_id is None or branch_id is None or oracle_commit_id is None:
            return domain_pb.ActivateSamplesResponse(created=False, commit_id="")

        async with SessionLocal() as session:
            branch_repo = BranchRepository(session)
            branch = await branch_repo.get_by_id(branch_id)
            if not branch or branch.project_id != project_id:
                return domain_pb.ActivateSamplesResponse(created=False, commit_id="")

            parent_commit_id = source_commit_id or branch.head_commit_id
            if parent_commit_id is None:
                return domain_pb.ActivateSamplesResponse(created=False, commit_id="")

            loop_uuid = _parse_uuid(request.loop_id)
            round_index = int(request.round_index or 0)
            if loop_uuid is None or round_index <= 0:
                return domain_pb.ActivateSamplesResponse(created=False, commit_id="")

            selected_sample_ids = await self._load_selected_sample_ids(
                session=session,
                loop_id=loop_uuid,
                round_index=round_index,
                topk=int(request.topk or 0),
            )
            if not selected_sample_ids:
                return domain_pb.ActivateSamplesResponse(created=False, commit_id="")

            activation_key = _build_activation_key(loop_uuid, round_index, selected_sample_ids)
            existing_commit = await self._find_existing_activation_commit_tx(
                session=session,
                project_id=project_id,
                activation_key=activation_key,
            )
            if existing_commit is not None:
                if branch.head_commit_id != existing_commit.id:
                    branch.head_commit_id = existing_commit.id
                    session.add(branch)
                    await session.commit()
                return domain_pb.ActivateSamplesResponse(created=False, commit_id=str(existing_commit.id))

            command_id = str(request.command_id or "").strip()
            if not command_id:
                command_id = f"activate:{activation_key}"

            commit = await self._create_simulation_commit_tx(
                session=session,
                project_id=project_id,
                oracle_commit_id=oracle_commit_id,
                parent_commit_id=parent_commit_id,
                selected_sample_ids=selected_sample_ids,
                command_id=command_id,
                activation_key=activation_key,
                loop_id=str(request.loop_id or ""),
                round_index=round_index,
                query_strategy=str(request.query_strategy or ""),
                topk=int(request.topk or 0),
                snapshot_id=str(request.snapshot_id or ""),
                selector_encoding=int(request.selector_encoding or 0),
                selector_cardinality=int(request.selector_cardinality or 0),
                selector_checksum=str(request.selector_checksum or ""),
            )
            await self._grow_train_selector_after_activation(
                session=session,
                loop_id=loop_uuid,
                round_id=None,
                round_index=round_index,
                snapshot_id=snapshot_uuid,
                selected_sample_ids=selected_sample_ids,
            )
            branch.head_commit_id = commit.id
            session.add(branch)
            await session.commit()
            return domain_pb.ActivateSamplesResponse(created=True, commit_id=str(commit.id))

    async def AdvanceBranchHead(self, request, context):  # noqa: N802
        branch_id = _parse_uuid(request.branch_id)
        to_commit_id = _parse_uuid(request.to_commit_id)
        if branch_id is None or to_commit_id is None:
            return domain_pb.AdvanceBranchHeadResponse(advanced=False, branch_id="", head_commit_id="")

        async with SessionLocal() as session:
            branch_repo = BranchRepository(session)
            commit_repo = CommitRepository(session)
            branch = await branch_repo.get_by_id(branch_id)
            commit = await commit_repo.get_by_id(to_commit_id)
            if not branch or not commit or commit.project_id != branch.project_id:
                return domain_pb.AdvanceBranchHeadResponse(advanced=False, branch_id="", head_commit_id="")

            branch.head_commit_id = to_commit_id
            session.add(branch)
            await session.commit()
            return domain_pb.AdvanceBranchHeadResponse(
                advanced=True,
                branch_id=str(branch.id),
                head_commit_id=str(to_commit_id),
            )

    async def QueryData(self, request, context):  # noqa: N802
        step_id = _resolve_step_id(request.step_id)
        response_messages = await self._runtime_ingress.handle_data_request(
            pb.DataRequest(
                request_id=str(request.request_id or ""),
                step_id=step_id,
                query_type=int(request.query_type),
                project_id=str(request.project_id or ""),
                commit_id=str(request.commit_id or ""),
                cursor=str(request.cursor or ""),
                limit=int(request.limit or 0),
                preferred_chunk_bytes=int(request.preferred_chunk_bytes or 0),
                max_uncompressed_bytes=int(request.max_uncompressed_bytes or 0),
            )
        )
        for response_message in response_messages:
            payload_type = response_message.WhichOneof("payload")
            if payload_type == "error":
                error_payload = response_message.error
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(str(error_payload.reason or error_payload.message or "query data failed"))
                return
            if payload_type != "data_response":
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("runtime ingress returned unexpected payload")
                return
            yield _to_domain_data_response(response_message.data_response)

    async def CreateUploadTicket(self, request, context):  # noqa: N802
        step_id = _resolve_step_id(request.step_id)
        response_message = await self._runtime_ingress.handle_upload_ticket_request(
            pb.UploadTicketRequest(
                request_id=str(request.request_id or ""),
                step_id=step_id,
                artifact_name=str(request.artifact_name or ""),
                content_type=str(request.content_type or "application/octet-stream"),
            )
        )
        payload_type = response_message.WhichOneof("payload")
        if payload_type == "error":
            error_payload = response_message.error
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(error_payload.reason or error_payload.message or "create upload ticket failed"))
            return domain_pb.UploadTicketResponse(
                request_id=str(request.request_id or ""),
                reply_to=str(request.request_id or ""),
                step_id=step_id,
                upload_url="",
                storage_uri="",
                headers={},
            )
        if payload_type != "upload_ticket_response":
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("runtime ingress returned unexpected payload")
            return domain_pb.UploadTicketResponse(
                request_id=str(request.request_id or ""),
                reply_to=str(request.request_id or ""),
                step_id=step_id,
                upload_url="",
                storage_uri="",
                headers={},
            )
        upload_ticket = response_message.upload_ticket_response
        upload_step_id = _resolve_step_id(upload_ticket.step_id)
        return domain_pb.UploadTicketResponse(
            request_id=str(upload_ticket.request_id or ""),
            reply_to=str(upload_ticket.reply_to or ""),
            step_id=upload_step_id,
            upload_url=str(upload_ticket.upload_url or ""),
            storage_uri=str(upload_ticket.storage_uri or ""),
            headers=dict(upload_ticket.headers),
        )


class RuntimeGrpcServer:
    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._runtime_domain_service = RuntimeDomainService()

    async def start(self) -> None:
        if self._server is not None:
            return
        if not settings.RUNTIME_DOMAIN_GRPC_SERVER_ENABLED:
            logger.info("runtime domain grpc startup skipped: service disabled")
            return

        self._server = grpc.aio.server()
        bind_address = settings.RUNTIME_DOMAIN_GRPC_BIND
        domain_pb_grpc.add_RuntimeDomainServicer_to_server(self._runtime_domain_service, self._server)

        self._server.add_insecure_port(bind_address)
        await self._server.start()
        logger.info("runtime domain grpc server started bind={}", bind_address)

    async def stop(self) -> None:
        if self._server is None:
            return
        await self._server.stop(grace=2)
        await self._server.wait_for_termination()
        self._server = None
        logger.info("runtime grpc server stopped")


runtime_grpc_server = RuntimeGrpcServer()
