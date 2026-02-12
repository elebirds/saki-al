"""Ingress service for runtime-control gRPC messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from loguru import logger
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.infra.db.session import SessionLocal
from saki_api.infra.grpc import runtime_codec
from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import ProjectDataset
from saki_api.modules.runtime.service.application.control_plane_dto import (
    RuntimeDataRequestDTO,
    RuntimeUploadTicketRequestDTO,
)
from saki_api.modules.runtime.service.application.event_dto import (
    RuntimeArtifactDTO,
    RuntimeTaskCandidateDTO,
    RuntimeTaskEventDTO,
    RuntimeTaskResultDTO,
)
from saki_api.modules.runtime.service.persistence.task_runtime_persistence_service import (
    RuntimeTaskPersistenceService,
)
from saki_api.modules.shared.modeling.enums import JobTaskStatus
from saki_api.modules.storage.domain.asset import Asset
from saki_api.modules.storage.domain.sample import Sample


@dataclass(slots=True)
class _InvalidRuntimeRequest(Exception):
    message: str
    reason: str


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

    async def handle_data_request(self, message: pb.DataRequest) -> pb.RuntimeMessage:
        try:
            request = self._decode_data_request(message)
        except _InvalidRuntimeRequest as exc:
            return runtime_codec.build_error_message(
                code="invalid_data_request",
                message=exc.message,
                reply_to=str(message.request_id or ""),
                task_id=str(message.task_id or ""),
                query_type=int(message.query_type),
                reason=exc.reason,
            )

        try:
            items, next_cursor = await self._query_data_items(
                query_type=request.query_type,
                project_id=request.project_id,
                commit_id=request.commit_id,
                limit=request.limit,
                offset=request.offset,
            )
        except Exception as exc:
            logger.exception(
                "data request failed request_id={} task_id={} error={}",
                request.request_id,
                request.task_id,
                exc,
            )
            return runtime_codec.build_error_message(
                code="data_query_failed",
                message="data query failed",
                reply_to=request.request_id,
                task_id=request.task_id,
                query_type=request.query_type,
                reason=str(exc),
            )

        return pb.RuntimeMessage(
            data_response=pb.DataResponse(
                request_id=str(uuid.uuid4()),
                reply_to=request.request_id,
                task_id=request.task_id,
                query_type=request.query_type,
                items=items,
                next_cursor=next_cursor or "",
            )
        )

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
            logger.exception("failed to issue upload ticket task_id={} error={}", request.task_id, exc)
            return runtime_codec.build_error_message(
                code="upload_ticket_failed",
                message="failed to issue upload ticket",
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

    async def persist_task_event(self, message: pb.TaskEvent) -> None:
        task_id = self._parse_uuid(message.task_id, "task_id")
        event_type, payload, status_enum = runtime_codec.decode_task_event(message)
        mapped_status = self._status_from_pb(status_enum) if status_enum is not None else None
        event_dto = RuntimeTaskEventDTO(
            task_id=task_id,
            seq=int(message.seq),
            ts=self._to_datetime_millis(int(message.ts)),
            event_type=event_type,
            payload=payload,
            status=mapped_status,
            request_id=str(message.request_id or "") or None,
        )

        async with self._session_local() as session:
            persistence = RuntimeTaskPersistenceService(session)
            await persistence.persist_task_event(event_dto)
            await session.commit()

    async def persist_task_result(self, message: pb.TaskResult) -> None:
        task_id = self._parse_uuid(message.task_id, "task_id")
        artifacts: list[RuntimeArtifactDTO] = [
            RuntimeArtifactDTO(
                name=str(item.name or ""),
                kind=str(item.kind or "artifact"),
                uri=str(item.uri or ""),
                meta=runtime_codec.struct_to_dict(item.meta),
            )
            for item in message.artifacts
            if str(item.name or "")
        ]

        candidates: list[RuntimeTaskCandidateDTO] = []
        for idx, candidate in enumerate(message.candidates, start=1):
            sample_id_raw = str(candidate.sample_id or "").strip()
            if not sample_id_raw:
                continue
            try:
                sample_id = uuid.UUID(sample_id_raw)
            except Exception:
                continue
            candidates.append(
                RuntimeTaskCandidateDTO(
                    sample_id=sample_id,
                    rank=idx,
                    score=float(candidate.score or 0.0),
                    reason=runtime_codec.struct_to_dict(candidate.reason),
                )
            )

        result_dto = RuntimeTaskResultDTO(
            task_id=task_id,
            status=self._status_from_pb(int(message.status)),
            metrics={str(k): float(v) for k, v in message.metrics.items()},
            artifacts=artifacts,
            candidates=candidates,
            last_error=str(message.error_message or "") or None,
        )

        async with self._session_local() as session:
            persistence = RuntimeTaskPersistenceService(session)
            await persistence.persist_task_result(result_dto)
            await session.commit()

    def _decode_data_request(self, message: pb.DataRequest) -> RuntimeDataRequestDTO:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        if not request_id or not task_id:
            raise _InvalidRuntimeRequest("request_id and task_id are required", "missing_required_field")

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
        )

    def _decode_upload_ticket_request(self, message: pb.UploadTicketRequest) -> RuntimeUploadTicketRequestDTO:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        artifact_name = str(message.artifact_name or "").strip()
        if not request_id or not task_id or not artifact_name:
            raise _InvalidRuntimeRequest(
                "request_id/task_id/artifact_name are required",
                "missing_required_field",
            )

        return RuntimeUploadTicketRequestDTO(
            request_id=request_id,
            task_id=task_id,
            artifact_name=artifact_name,
            content_type=str(message.content_type or "application/octet-stream"),
        )

    async def _query_data_items(
            self,
            *,
            query_type: int,
            project_id: uuid.UUID,
            commit_id: uuid.UUID,
            limit: int,
            offset: int,
    ) -> tuple[list[pb.DataItem], str | None]:
        async with self._session_local() as session:
            if query_type == pb.LABELS:
                rows = list(
                    (
                        await session.exec(
                            select(Label)
                            .where(Label.project_id == project_id)
                            .order_by(Label.id)
                            .offset(offset)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                page, next_cursor = self._paginate(rows, limit=limit, offset=offset)
                items = [
                    pb.DataItem(label_item=pb.LabelItem(id=str(item.id), name=item.name or "", color=item.color or ""))
                    for item in page
                ]
                return items, next_cursor

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
                    return [], None

                base_stmt = select(Sample).where(Sample.dataset_id.in_(dataset_ids))
                if query_type == pb.UNLABELED_SAMPLES:
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

                items: list[pb.DataItem] = []
                for sample in page:
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
                    items.append(
                        pb.DataItem(
                            sample_item=pb.SampleItem(
                                id=str(sample.id),
                                asset_hash=asset_hash,
                                download_url=download_url,
                                width=width,
                                height=height,
                                meta=runtime_codec.dict_to_struct(sample.meta_info or {}),
                            )
                        )
                    )
                return items, next_cursor

            if query_type == pb.ANNOTATIONS:
                rows = list(
                    (
                        await session.exec(
                            select(Annotation)
                            .join(
                                CommitAnnotationMap,
                                (CommitAnnotationMap.annotation_id == Annotation.id)
                                & (CommitAnnotationMap.commit_id == commit_id),
                            )
                            .order_by(Annotation.id)
                            .offset(offset)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                page, next_cursor = self._paginate(rows, limit=limit, offset=offset)
                items: list[pb.DataItem] = []
                for ann in page:
                    payload = dict(ann.data or {})
                    bbox_xywh = [
                        float(payload.get("x", 0.0)),
                        float(payload.get("y", 0.0)),
                        float(payload.get("width", 0.0)),
                        float(payload.get("height", 0.0)),
                    ]
                    items.append(
                        pb.DataItem(
                            annotation_item=pb.AnnotationItem(
                                id=str(ann.id),
                                sample_id=str(ann.sample_id),
                                category_id=str(ann.label_id),
                                bbox_xywh=bbox_xywh,
                                obb=runtime_codec.dict_to_struct(
                                    payload.get("obb") if isinstance(payload.get("obb"), dict) else {}
                                ),
                                source=str(ann.source.value if hasattr(ann.source, "value") else ann.source),
                                confidence=float(ann.confidence or 0.0),
                            )
                        )
                    )
                return items, next_cursor

            raise RuntimeError(f"unsupported query_type={query_type}")

    @staticmethod
    def _parse_uuid(raw: str | None, field_name: str) -> uuid.UUID:
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"{field_name} is required")
        try:
            return uuid.UUID(value)
        except Exception as exc:
            raise ValueError(f"invalid {field_name}: {value}") from exc

    @staticmethod
    def _status_from_pb(status: int) -> JobTaskStatus:
        mapping = {
            pb.PENDING: JobTaskStatus.PENDING,
            pb.DISPATCHING: JobTaskStatus.DISPATCHING,
            pb.RUNNING: JobTaskStatus.RUNNING,
            pb.RETRYING: JobTaskStatus.RETRYING,
            pb.SUCCEEDED: JobTaskStatus.SUCCEEDED,
            pb.FAILED: JobTaskStatus.FAILED,
            pb.CANCELLED: JobTaskStatus.CANCELLED,
            pb.SKIPPED: JobTaskStatus.SKIPPED,
        }
        return mapping.get(int(status), JobTaskStatus.PENDING)

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
