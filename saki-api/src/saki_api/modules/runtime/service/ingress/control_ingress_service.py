"""Ingress service for runtime-control gRPC messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from loguru import logger
from sqlmodel import select

from saki_ir.codec import encode_payload
from saki_ir import IRValidationError, normalize_prediction_snapshot, parse_geometry
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb
from saki_ir.transport import DEFAULT_CHUNK_BYTES, split_encoded_payload
from saki_api.core.config import settings
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.infra.db.session import SessionLocal
from saki_api.infra.grpc import runtime_codec
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import ProjectDataset
from saki_api.modules.runtime.domain.al_loop_visibility import ALLoopVisibility
from saki_api.modules.runtime.domain.al_round_selection_override import ALRoundSelectionOverride
from saki_api.modules.runtime.domain.al_snapshot_sample import ALSnapshotSample
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.service.application.control_plane_dto import (
    RuntimeDataRequestDTO,
    RuntimeUploadTicketRequestDTO,
)
from saki_api.modules.shared.modeling.enums import (
    LoopMode,
    SnapshotPartition,
    StepType,
    SnapshotValPolicy,
)
from saki_api.modules.storage.domain.asset import Asset
from saki_api.modules.storage.domain.sample import Sample


@dataclass(slots=True)
class _InvalidRuntimeRequest(Exception):
    message: str
    reason: str


_MIN_CHUNK_BYTES = 64 * 1024
_SERVER_MAX_CHUNK_BYTES = 1024 * 1024
_DEFAULT_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


class RuntimeControlIngressService:
    """Domain-facing handler for runtime-control ingress payloads."""

    def __init__(
            self,
            *,
            session_local=SessionLocal,
            storage_resolver: Callable[[], object] | None = None,
    ) -> None:
        self._session_local = session_local
        self._storage_resolver = storage_resolver
        self._storage = None

    @property
    def storage(self):
        if self._storage_resolver is not None:
            return self._storage_resolver()
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def handle_data_request(self, message: pb.DataRequest) -> list[pb.RuntimeMessage]:
        try:
            request = self._decode_data_request(message)
        except _InvalidRuntimeRequest as exc:
            return [
                runtime_codec.build_error_message(
                    code="invalid_data_request",
                    message=exc.message,
                    reply_to=str(message.request_id or ""),
                    task_id=str(message.task_id or ""),
                    query_type=int(message.query_type),
                    reason=exc.reason,
                )
            ]

        try:
            batch, next_cursor = await self._query_data_batch(
                query_type=request.query_type,
                task_id=request.task_id,
                project_id=request.project_id,
                commit_id=request.commit_id,
                limit=request.limit,
                offset=request.offset,
            )
        except Exception as exc:
            logger.exception(
                "数据请求失败 request_id={} task_id={} error={}",
                request.request_id,
                request.task_id,
                exc,
            )
            return [
                runtime_codec.build_error_message(
                    code="data_query_failed",
                    message="数据查询失败",
                    reply_to=request.request_id,
                    task_id=request.task_id,
                    query_type=request.query_type,
                    reason=str(exc),
                )
            ]

        encoded = encode_payload(batch)
        chunk_bytes = self._effective_chunk_bytes(request.preferred_chunk_bytes)
        chunks = split_encoded_payload(encoded, chunk_bytes=chunk_bytes)

        responses: list[pb.RuntimeMessage] = []
        for chunk in chunks:
            is_last = bool(chunk["is_last_chunk"])
            responses.append(
                pb.RuntimeMessage(
                    data_response=pb.DataResponse(
                        request_id=str(uuid.uuid4()),
                        reply_to=request.request_id,
                        task_id=request.task_id,
                        query_type=request.query_type,
                        payload_id=chunk["payload_id"],
                        chunk_index=chunk["chunk_index"],
                        chunk_count=chunk["chunk_count"],
                        header_proto=chunk["header_proto"],
                        payload_chunk=chunk["payload_chunk"],
                        payload_total_size=chunk["payload_total_size"],
                        payload_checksum_crc32c=chunk["payload_checksum_crc32c"],
                        chunk_checksum_crc32c=chunk["chunk_checksum_crc32c"],
                        next_cursor=(next_cursor or "") if is_last else "",
                        is_last_chunk=is_last,
                    )
                )
            )
        return responses

    async def handle_upload_ticket_request(self, message: pb.UploadTicketRequest) -> pb.RuntimeMessage:
        try:
            request = self._decode_upload_ticket_request(message)
        except _InvalidRuntimeRequest as exc:
            return runtime_codec.build_error_message(
                code="invalid_upload_ticket_request",
                message=exc.message,
                reply_to=str(message.request_id or ""),
                task_id=str(message.task_id or ""),
                reason=exc.reason,
            )

        object_name = f"runtime/tasks/{request.task_id}/{request.artifact_name}"
        try:
            upload_url = self.storage.get_presigned_put_url(
                object_name=object_name,
                expires_delta=timedelta(hours=settings.RUNTIME_UPLOAD_URL_EXPIRE_HOURS),
            )
        except Exception as exc:
            logger.exception("生成上传凭证失败 task_id={} error={}", request.task_id, exc)
            return runtime_codec.build_error_message(
                code="upload_ticket_failed",
                message="生成上传凭证失败",
                reply_to=request.request_id,
                task_id=request.task_id,
                reason=str(exc),
            )

        storage_uri = f"s3://{settings.MINIO_BUCKET_NAME}/{object_name}"
        return pb.RuntimeMessage(
            upload_ticket_response=pb.UploadTicketResponse(
                request_id=str(uuid.uuid4()),
                reply_to=request.request_id,
                task_id=request.task_id,
                upload_url=upload_url,
                storage_uri=storage_uri,
                headers={"Content-Type": request.content_type},
            )
        )

    def _decode_data_request(self, message: pb.DataRequest) -> RuntimeDataRequestDTO:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        if not request_id or not task_id:
            raise _InvalidRuntimeRequest("request_id 和 task_id 为必填", "missing_required_field")

        try:
            project_id = self._parse_uuid(str(message.project_id or ""), "project_id")
            commit_id = self._parse_uuid(str(message.commit_id or ""), "commit_id")
        except ValueError as exc:
            raise _InvalidRuntimeRequest(str(exc), "invalid_uuid") from exc

        return RuntimeDataRequestDTO(
            request_id=request_id,
            task_id=task_id,
            query_type=int(message.query_type),
            project_id=project_id,
            commit_id=commit_id,
            limit=max(1, min(int(message.limit or 1000), 5000)),
            offset=self._parse_cursor(message.cursor),
            preferred_chunk_bytes=max(0, int(message.preferred_chunk_bytes or 0)),
            max_uncompressed_bytes=max(0, int(message.max_uncompressed_bytes or _DEFAULT_MAX_UNCOMPRESSED_BYTES)),
        )

    def _decode_upload_ticket_request(self, message: pb.UploadTicketRequest) -> RuntimeUploadTicketRequestDTO:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        artifact_name = str(message.artifact_name or "").strip()
        if not request_id or not task_id or not artifact_name:
            raise _InvalidRuntimeRequest(
                "request_id/task_id/artifact_name 为必填",
                "missing_required_field",
            )

        return RuntimeUploadTicketRequestDTO(
            request_id=request_id,
            task_id=task_id,
            artifact_name=artifact_name,
            content_type=str(message.content_type or "application/octet-stream"),
        )

    async def _query_data_batch(
            self,
            *,
            query_type: int,
            task_id: str,
            project_id: uuid.UUID,
            commit_id: uuid.UUID,
            limit: int,
            offset: int,
    ) -> tuple[irpb.DataBatchIR, str | None]:
        async with self._session_local() as session:
            if query_type == pb.LABELS:
                rows = list(
                    (
                        await session.exec(
                            select(Label)
                            .where(Label.project_id == project_id)
                            .order_by(Label.sort_order.asc(), Label.id.asc())
                            .offset(offset)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                page, next_cursor = self._paginate(rows, limit=limit, offset=offset)
                items = [
                    irpb.DataItemIR(
                        label=irpb.LabelRecord(
                            id=str(item.id),
                            name=item.name or "",
                            color=item.color or "",
                        )
                    )
                    for item in page
                ]
                return irpb.DataBatchIR(items=items), next_cursor

            snapshot_scope_sample_ids: set[uuid.UUID] | None = None
            snapshot_split_hints: dict[str, str] | None = None
            snapshot_partition_hints: dict[str, str] | None = None
            if query_type in {pb.SAMPLES, pb.UNLABELED_SAMPLES, pb.ANNOTATIONS}:
                loop_id, mode, step_type, snapshot = await self._resolve_task_snapshot_scope(
                    session=session,
                    task_id=task_id,
                    project_id=project_id,
                )
                if (
                    loop_id is not None
                    and mode in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION}
                    and snapshot is not None
                ):
                    visible_ids = {
                        row[0] if isinstance(row, (tuple, list)) else row
                        for row in (
                            await session.exec(
                                select(ALLoopVisibility.sample_id)
                                .where(
                                    ALLoopVisibility.loop_id == loop_id,
                                    ALLoopVisibility.visible_in_train.is_(True),
                                )
                            )
                        ).all()
                    }
                    if query_type == pb.UNLABELED_SAMPLES:
                        pool_ids = {
                            row[0] if isinstance(row, (tuple, list)) else row
                            for row in (
                                await session.exec(
                                    select(ALSnapshotSample.sample_id).where(
                                        ALSnapshotSample.snapshot_version_id == snapshot.id,
                                        ALSnapshotSample.partition == SnapshotPartition.TRAIN_POOL,
                                    )
                                )
                            ).all()
                        }
                        snapshot_scope_sample_ids = pool_ids.difference(visible_ids)
                    else:
                        step_type_text = str(
                            step_type.value if hasattr(step_type, "value") else step_type
                        ).strip().lower()
                        if step_type_text == StepType.EVAL.value.lower():
                            test_anchor_ids = {
                                row[0] if isinstance(row, (tuple, list)) else row
                                for row in (
                                    await session.exec(
                                        select(ALSnapshotSample.sample_id).where(
                                            ALSnapshotSample.snapshot_version_id == snapshot.id,
                                            ALSnapshotSample.partition == SnapshotPartition.TEST_ANCHOR,
                                        )
                                    )
                                ).all()
                            }
                            test_batch_ids = {
                                row[0] if isinstance(row, (tuple, list)) else row
                                for row in (
                                    await session.exec(
                                        select(ALSnapshotSample.sample_id).where(
                                            ALSnapshotSample.snapshot_version_id == snapshot.id,
                                            ALSnapshotSample.partition == SnapshotPartition.TEST_BATCH,
                                        )
                                    )
                                ).all()
                            }
                            snapshot_scope_sample_ids = test_anchor_ids.union(test_batch_ids)
                            snapshot_partition_hints = {
                                str(sample_id): SnapshotPartition.TEST_ANCHOR.value.lower()
                                for sample_id in test_anchor_ids
                            }
                            snapshot_partition_hints.update(
                                {
                                    str(sample_id): SnapshotPartition.TEST_BATCH.value.lower()
                                    for sample_id in test_batch_ids
                                }
                            )
                        else:
                            val_partitions = [SnapshotPartition.VAL_ANCHOR]
                            if snapshot.val_policy == SnapshotValPolicy.EXPAND_WITH_BATCH_VAL:
                                val_partitions.append(SnapshotPartition.VAL_BATCH)
                            val_ids = {
                                row[0] if isinstance(row, (tuple, list)) else row
                                for row in (
                                    await session.exec(
                                        select(ALSnapshotSample.sample_id).where(
                                            ALSnapshotSample.snapshot_version_id == snapshot.id,
                                            ALSnapshotSample.partition.in_(val_partitions),
                                        )
                                    )
                                ).all()
                            }
                            snapshot_scope_sample_ids = visible_ids.union(val_ids)
                            snapshot_split_hints = {str(sample_id): "train" for sample_id in visible_ids}
                            snapshot_split_hints.update({str(sample_id): "val" for sample_id in val_ids})

            if query_type in {pb.SAMPLES, pb.UNLABELED_SAMPLES}:
                dataset_ids = [
                    row[0] if isinstance(row, (tuple, list)) else row
                    for row in (
                        await session.exec(
                            select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
                        )
                    ).all()
                ]
                if not dataset_ids:
                    return irpb.DataBatchIR(), None

                base_stmt = select(Sample).where(Sample.dataset_id.in_(dataset_ids))
                if snapshot_scope_sample_ids is not None:
                    if not snapshot_scope_sample_ids:
                        return irpb.DataBatchIR(), None
                    base_stmt = base_stmt.where(Sample.id.in_(list(snapshot_scope_sample_ids)))
                elif query_type == pb.UNLABELED_SAMPLES:
                    labeled_ids = [
                        row[0] if isinstance(row, (tuple, list)) else row
                        for row in (
                            await session.exec(
                                select(CommitAnnotationMap.sample_id)
                                .where(CommitAnnotationMap.commit_id == commit_id)
                                .distinct()
                            )
                        ).all()
                    ]
                    if labeled_ids:
                        base_stmt = base_stmt.where(Sample.id.notin_(labeled_ids))

                rows = list(
                    (
                        await session.exec(
                            base_stmt.order_by(Sample.id).offset(offset).limit(limit + 1)
                        )
                    ).all()
                )
                page, next_cursor = self._paginate(rows, limit=limit, offset=offset)
                items = await self._to_sample_items(
                    session=session,
                    samples=page,
                    snapshot_split_hints=snapshot_split_hints,
                    snapshot_partition_hints=snapshot_partition_hints,
                )
                return irpb.DataBatchIR(items=items), next_cursor

            if query_type == pb.ANNOTATIONS:
                base_stmt = select(Annotation).join(
                    CommitAnnotationMap,
                    (CommitAnnotationMap.annotation_id == Annotation.id)
                    & (CommitAnnotationMap.commit_id == commit_id),
                )
                if snapshot_scope_sample_ids is not None:
                    if not snapshot_scope_sample_ids:
                        return irpb.DataBatchIR(), None
                    base_stmt = base_stmt.where(Annotation.sample_id.in_(list(snapshot_scope_sample_ids)))
                rows = list(
                    (
                        await session.exec(
                            base_stmt.order_by(Annotation.id).offset(offset).limit(limit + 1)
                        )
                    ).all()
                )
                page, next_cursor = self._paginate(rows, limit=limit, offset=offset)
                items = self._to_annotation_items(page)
                return irpb.DataBatchIR(items=items), next_cursor

            raise RuntimeError(f"unsupported query_type={query_type}")

    async def _resolve_task_snapshot_scope(
            self,
            *,
            session,
            task_id: str,
            project_id: uuid.UUID,
    ) -> tuple[uuid.UUID | None, LoopMode | None, StepType | None, ALSnapshotVersion | None]:
        try:
            task_uuid = uuid.UUID(str(task_id or "").strip())
        except Exception:
            return None, None, None, None
        row = (
            await session.exec(
                select(
                    Round.loop_id,
                    Loop.mode,
                    Step.step_type,
                    Loop.active_snapshot_version_id,
                )
                .select_from(Step)
                .join(Round, Round.id == Step.round_id)
                .join(Loop, Loop.id == Round.loop_id)
                .where(
                    Step.task_id == task_uuid,
                    Round.project_id == project_id,
                )
                .limit(1)
            )
        ).first()
        if not row:
            return None, None, None, None
        loop_id, mode, step_type, snapshot_version_id = row
        if mode not in {LoopMode.ACTIVE_LEARNING, LoopMode.SIMULATION} or not snapshot_version_id:
            return loop_id, mode, step_type, None
        snapshot = await session.get(ALSnapshotVersion, snapshot_version_id)
        if not snapshot:
            return loop_id, mode, step_type, None
        return loop_id, mode, step_type, snapshot

    async def _to_sample_items(
        self,
        *,
        session,
        samples: list[Sample],
        snapshot_split_hints: dict[str, str] | None = None,
        snapshot_partition_hints: dict[str, str] | None = None,
    ) -> list[irpb.DataItemIR]:
        items: list[irpb.DataItemIR] = []
        for sample in samples:
            width = int((sample.meta_info or {}).get("width") or 0)
            height = int((sample.meta_info or {}).get("height") or 0)
            download_url = ""
            asset_hash = ""
            if sample.primary_asset_id:
                asset = await session.get(Asset, sample.primary_asset_id)
                if asset:
                    asset_hash = str(asset.hash or "")
                    try:
                        download_url = self.storage.get_presigned_url(
                            object_name=str(asset.path),
                            expires_delta=timedelta(hours=settings.RUNTIME_UPLOAD_URL_EXPIRE_HOURS),
                        )
                    except Exception:
                        download_url = ""
            meta_payload = dict(sample.meta_info or {})
            if snapshot_split_hints:
                split_hint = snapshot_split_hints.get(str(sample.id))
                if split_hint in {"train", "val"}:
                    meta_payload["_snapshot_split"] = split_hint
            if snapshot_partition_hints:
                partition_hint = snapshot_partition_hints.get(str(sample.id))
                if partition_hint:
                    meta_payload["_snapshot_partition"] = partition_hint
            items.append(
                irpb.DataItemIR(
                    sample=irpb.SampleRecord(
                        id=str(sample.id),
                        asset_hash=asset_hash,
                        download_url=download_url,
                        width=width,
                        height=height,
                        meta=runtime_codec.dict_to_struct(meta_payload),
                    )
                )
            )
        return items

    def _to_annotation_items(self, annotations: list[Annotation]) -> list[irpb.DataItemIR]:
        items: list[irpb.DataItemIR] = []
        for ann in annotations:
            try:
                geometry = parse_geometry(dict(ann.geometry or {}))
            except Exception as exc:
                raise RuntimeError(f"invalid annotation geometry id={ann.id}") from exc

            items.append(
                irpb.DataItemIR(
                    annotation=irpb.AnnotationRecord(
                        id=str(ann.id),
                        sample_id=str(ann.sample_id),
                        label_id=str(ann.label_id),
                        geometry=geometry,
                        source=self._annotation_source_to_ir_enum(
                            str(ann.source.value if hasattr(ann.source, "value") else ann.source)
                        ),
                        confidence=float(ann.confidence or 0.0),
                        attrs=runtime_codec.dict_to_struct(
                            ann.attrs if isinstance(ann.attrs, dict) else {}
                        ),
                    )
                )
            )
        return items

    @staticmethod
    def _annotation_source_to_ir_enum(source: str) -> irpb.AnnotationSource:
        val = (source or "").strip().lower()
        if val == "manual":
            return irpb.ANNOTATION_SOURCE_MANUAL
        if val == "model":
            return irpb.ANNOTATION_SOURCE_MODEL
        if val == "confirmed_model":
            return irpb.ANNOTATION_SOURCE_CONFIRMED_MODEL
        if val == "system":
            return irpb.ANNOTATION_SOURCE_SYSTEM
        if val == "imported":
            return irpb.ANNOTATION_SOURCE_IMPORTED
        return irpb.ANNOTATION_SOURCE_UNSPECIFIED

    @staticmethod
    def _effective_chunk_bytes(preferred: int) -> int:
        requested = int(preferred) if preferred > 0 else DEFAULT_CHUNK_BYTES
        effective = min(requested, _SERVER_MAX_CHUNK_BYTES, DEFAULT_CHUNK_BYTES)
        return max(_MIN_CHUNK_BYTES, effective)

    @staticmethod
    def _parse_uuid(raw: str | None, field_name: str) -> uuid.UUID:
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"{field_name} 为必填")
        try:
            return uuid.UUID(value)
        except Exception as exc:
            raise ValueError(f"无效的 {field_name}: {value}") from exc

    @staticmethod
    def _to_datetime_millis(ts: int) -> datetime:
        if int(ts) <= 0:
            return datetime.now(UTC)
        return datetime.fromtimestamp(float(ts) / 1000.0, tz=UTC)

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            return max(0, int(cursor))
        except Exception:
            return 0

    @staticmethod
    def _paginate(rows: list[object], *, limit: int, offset: int) -> tuple[list[object], str | None]:
        page = rows
        next_cursor: str | None = None
        if len(page) > limit:
            page = page[:limit]
            next_cursor = str(offset + limit)
        return page, next_cursor
