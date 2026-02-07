"""
Runtime control gRPC server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Optional

import grpc
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_control_pb2_grpc as pb_grpc
from saki_api.models.enums import AnnotationType, AnnotationBatchStatus, TrainingJobStatus
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import ProjectDataset
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.services.loop_config import normalize_loop_global_config
from saki_api.utils.storage import get_storage_provider

logger = logging.getLogger(__name__)


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except Exception:
        return 0


def _parse_uuid(raw: str | None, field_name: str) -> uuid.UUID:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return uuid.UUID(value)
    except Exception as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc


def _to_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_obb_payload(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    required_fields = {"cx", "cy", "w", "h", "angle_deg", "normalized"}
    if not required_fields.issubset(data.keys()):
        return {}
    if not _to_bool(data.get("normalized"), False):
        return {}

    cx = _to_float(data.get("cx"), 0.0)
    cy = _to_float(data.get("cy"), 0.0)
    w = _to_float(data.get("w"), 0.0)
    h = _to_float(data.get("h"), 0.0)
    angle_deg = _to_float(data.get("angle_deg"), 0.0)
    if w <= 0.0 or h <= 0.0:
        return {}

    return {
        "cx": cx,
        "cy": cy,
        "w": w,
        "h": h,
        "angle_deg": angle_deg,
        "normalized": True,
    }


def _map_status(status: int | str) -> TrainingJobStatus:
    if isinstance(status, str):
        status = runtime_codec.text_to_status(status)

    mapping = {
        pb.CREATED: TrainingJobStatus.PENDING,
        pb.QUEUED: TrainingJobStatus.PENDING,
        pb.RUNNING: TrainingJobStatus.RUNNING,
        pb.STOPPING: TrainingJobStatus.RUNNING,
        pb.STOPPED: TrainingJobStatus.CANCELLED,
        pb.SUCCEEDED: TrainingJobStatus.SUCCESS,
        pb.FAILED: TrainingJobStatus.FAILED,
    }
    return mapping.get(int(status), TrainingJobStatus.PENDING)


class _RequestDedupCache:
    def __init__(self, *, ttl_sec: int, max_entries: int) -> None:
        self._ttl_sec = max(1, int(ttl_sec))
        self._max_entries = max(64, int(max_entries))
        self._entries: OrderedDict[str, tuple[str, float, pb.RuntimeMessage | None]] = OrderedDict()

    @staticmethod
    def _clone_message(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        cloned = pb.RuntimeMessage()
        cloned.CopyFrom(message)
        return cloned

    def _evict(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, (_, expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired_keys:
            self._entries.pop(key, None)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def get(self, request_id: str, payload_type: str) -> tuple[bool, pb.RuntimeMessage | None]:
        if not request_id:
            return False, None

        self._evict()
        cached = self._entries.get(request_id)
        if cached is None:
            return False, None

        cached_payload, expires_at, response = cached
        if cached_payload != payload_type:
            return False, None
        if expires_at <= time.monotonic():
            self._entries.pop(request_id, None)
            return False, None

        self._entries.move_to_end(request_id)
        if response is None:
            return True, None
        return True, self._clone_message(response)

    def remember(
        self,
        request_id: str,
        payload_type: str,
        *,
        response: pb.RuntimeMessage | None = None,
    ) -> None:
        if not request_id:
            return
        stored_response = self._clone_message(response) if response is not None else None
        self._entries[request_id] = (
            payload_type,
            time.monotonic() + self._ttl_sec,
            stored_response,
        )
        self._entries.move_to_end(request_id)
        self._evict()


class RuntimeControlService(pb_grpc.RuntimeControlServicer):
    def __init__(self) -> None:
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    @staticmethod
    def _error_details(
            *,
            reason: str,
            request_id: str | None = None,
            reply_to: str | None = None,
            job_id: str | None = None,
            query_type: str | None = None,
            ack_for: str | None = None,
    ) -> dict[str, str]:
        details: dict[str, str] = {"reason": reason}
        if request_id:
            details["request_id"] = request_id
        if reply_to:
            details["reply_to"] = reply_to
        if job_id:
            details["job_id"] = job_id
        if query_type:
            details["query_type"] = query_type
        if ack_for:
            details["ack_for"] = ack_for
        return details

    async def Stream(self, request_iterator, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("x-internal-token") != settings.INTERNAL_TOKEN:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")

        outbox: asyncio.Queue[pb.RuntimeMessage] = asyncio.Queue()
        executor_id: Optional[str] = None
        close_stream_after_flush = False
        dedup_cache = _RequestDedupCache(
            ttl_sec=settings.RUNTIME_REQUEST_IDEMPOTENCY_TTL_SEC,
            max_entries=settings.RUNTIME_REQUEST_IDEMPOTENCY_MAX_ENTRIES,
        )

        async def _reader() -> None:
            nonlocal executor_id, close_stream_after_flush
            async for message in request_iterator:
                try:
                    payload_type = message.WhichOneof("payload")

                    if payload_type == "register":
                        register = message.register
                        executor_id = str(register.executor_id or "")
                        if not executor_id:
                            await outbox.put(
                                runtime_codec.build_error_message(
                                    code="INVALID_ARGUMENT",
                                    message="executor_id is required",
                                    details=self._error_details(
                                        reason="executor_id is required",
                                        request_id=register.request_id,
                                        reply_to=register.request_id,
                                    ),
                                )
                            )
                            if settings.RUNTIME_STREAM_REJECT_CLOSE:
                                close_stream_after_flush = True
                                break
                            continue

                        plugin_ids = {str(item.plugin_id) for item in register.plugins if item.plugin_id}
                        resources = runtime_codec.resource_summary_to_dict(register.resources)
                        try:
                            await runtime_dispatcher.register(
                                executor_id=executor_id,
                                queue=outbox,
                                version=str(register.version or ""),
                                plugin_ids=plugin_ids,
                                resources=resources,
                            )
                        except PermissionError as exc:
                            await outbox.put(
                                runtime_codec.build_error_message(
                                    code="FORBIDDEN",
                                    message=str(exc),
                                    details=self._error_details(
                                        reason=str(exc),
                                        request_id=register.request_id,
                                        reply_to=register.request_id,
                                    ),
                                )
                            )
                            if settings.RUNTIME_STREAM_REJECT_CLOSE:
                                close_stream_after_flush = True
                                break
                            continue
                        except Exception as exc:
                            await outbox.put(
                                runtime_codec.build_error_message(
                                    code="INTERNAL",
                                    message=f"register failed: {exc}",
                                    details=self._error_details(
                                        reason=f"register failed: {exc}",
                                        request_id=register.request_id,
                                        reply_to=register.request_id,
                                    ),
                                )
                            )
                            if settings.RUNTIME_STREAM_REJECT_CLOSE:
                                close_stream_after_flush = True
                                break
                            continue

                        await outbox.put(
                            runtime_codec.build_ack_message(
                                ack_for=register.request_id,
                                status=pb.OK,
                                message="registered",
                            )
                        )
                        continue

                    if payload_type == "heartbeat":
                        heartbeat = message.heartbeat
                        if not executor_id:
                            continue
                        await runtime_dispatcher.heartbeat(
                            executor_id=executor_id,
                            busy=bool(heartbeat.busy),
                            current_job_id=heartbeat.current_job_id or None,
                            resources=runtime_codec.resource_summary_to_dict(heartbeat.resources),
                        )
                        continue

                    if payload_type == "job_event":
                        request = message.job_event
                        request_id = str(request.request_id or "")
                        duplicated, _ = dedup_cache.get(request_id, "job_event")
                        if duplicated:
                            logger.info("忽略重复 job_event request_id=%s", request_id)
                            continue

                        await self._persist_job_event(request)
                        if request_id:
                            dedup_cache.remember(request_id, "job_event")
                        continue

                    if payload_type == "job_result":
                        request = message.job_result
                        request_id = str(request.request_id or "")
                        duplicated, _ = dedup_cache.get(request_id, "job_result")
                        if duplicated:
                            logger.info("忽略重复 job_result request_id=%s", request_id)
                            continue

                        await self._persist_job_result(request)
                        if executor_id:
                            await runtime_dispatcher.mark_executor_idle(
                                executor_id=executor_id,
                                job_id=request.job_id,
                            )
                        if request_id:
                            dedup_cache.remember(request_id, "job_result")
                        continue

                    if payload_type == "data_request":
                        request = message.data_request
                        request_id = str(request.request_id or "")
                        duplicated, cached_response = dedup_cache.get(request_id, "data_request")
                        if duplicated:
                            if cached_response is not None:
                                await outbox.put(cached_response)
                            logger.info("命中 data_request 幂等缓存 request_id=%s", request_id)
                            continue
                        try:
                            response = await self._build_data_response(request)
                        except ValueError as exc:
                            response = runtime_codec.build_error_message(
                                code="INVALID_ARGUMENT",
                                message=str(exc),
                                details=self._error_details(
                                    reason=str(exc),
                                    request_id=request.request_id,
                                    reply_to=request.request_id,
                                    job_id=request.job_id,
                                    query_type=runtime_codec.query_type_to_text(request.query_type),
                                ),
                            )
                        except Exception as exc:
                            response = runtime_codec.build_error_message(
                                code="INTERNAL",
                                message=f"data request failed: {exc}",
                                details=self._error_details(
                                    reason=f"data request failed: {exc}",
                                    request_id=request.request_id,
                                    reply_to=request.request_id,
                                    job_id=request.job_id,
                                    query_type=runtime_codec.query_type_to_text(request.query_type),
                                ),
                            )
                        await outbox.put(response)
                        if request_id:
                            dedup_cache.remember(request_id, "data_request", response=response)
                        continue

                    if payload_type == "upload_ticket_request":
                        request = message.upload_ticket_request
                        request_id = str(request.request_id or "")
                        duplicated, cached_response = dedup_cache.get(request_id, "upload_ticket_request")
                        if duplicated:
                            if cached_response is not None:
                                await outbox.put(cached_response)
                            logger.info("命中 upload_ticket_request 幂等缓存 request_id=%s", request_id)
                            continue
                        try:
                            response = await self._build_upload_ticket_response(request)
                        except ValueError as exc:
                            response = runtime_codec.build_error_message(
                                code="INVALID_ARGUMENT",
                                message=str(exc),
                                details=self._error_details(
                                    reason=str(exc),
                                    request_id=request.request_id,
                                    reply_to=request.request_id,
                                    job_id=request.job_id,
                                ),
                            )
                        except Exception as exc:
                            response = runtime_codec.build_error_message(
                                code="INTERNAL",
                                message=f"upload ticket failed: {exc}",
                                details=self._error_details(
                                    reason=f"upload ticket failed: {exc}",
                                    request_id=request.request_id,
                                    reply_to=request.request_id,
                                    job_id=request.job_id,
                                ),
                            )
                        await outbox.put(response)
                        if request_id:
                            dedup_cache.remember(request_id, "upload_ticket_request", response=response)
                        continue

                    if payload_type == "ack":
                        ack = message.ack
                        request_id = str(ack.request_id or "")
                        duplicated, _ = dedup_cache.get(request_id, "ack")
                        if duplicated:
                            logger.info("忽略重复 ack request_id=%s ack_for=%s", request_id, ack.ack_for)
                            continue
                        await runtime_dispatcher.handle_ack(
                            ack_for=str(ack.ack_for or ""),
                            status=int(ack.status),
                            message=ack.message or None,
                        )
                        if request_id:
                            dedup_cache.remember(request_id, "ack")
                        continue

                    if payload_type == "error":
                        err = message.error
                        logger.error(
                            "Executor error message: code=%s message=%s details=%s",
                            err.code,
                            err.message,
                            runtime_codec.struct_to_dict(err.details),
                        )
                        continue

                    logger.warning("Unknown runtime payload type: %s", payload_type)
                except Exception:
                    logger.exception("Failed to process runtime message")

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                if reader_task.done() and outbox.empty():
                    break
                try:
                    payload = await asyncio.wait_for(outbox.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if close_stream_after_flush and outbox.empty():
                        break
                    continue
                yield payload
                if close_stream_after_flush and outbox.empty():
                    break
        finally:
            reader_task.cancel()
            if executor_id:
                await runtime_dispatcher.unregister(executor_id)

    async def _persist_job_event(self, message: pb.JobEvent) -> None:
        job_id_raw = message.job_id
        if not job_id_raw:
            return
        try:
            job_id = uuid.UUID(str(job_id_raw))
        except Exception:
            return

        seq = int(message.seq or 0)
        if seq <= 0:
            return

        event_ts = datetime.fromtimestamp(int(message.ts or int(datetime.now(UTC).timestamp())), UTC)
        event_type, payload, status_enum = runtime_codec.decode_job_event(message)

        async with SessionLocal() as session:
            exists_stmt = select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.seq == seq)
            if (await session.exec(exists_stmt)).first():
                return

            job = await session.get(Job, job_id)
            if not job:
                return

            event = JobEvent(
                job_id=job_id,
                seq=seq,
                ts=event_ts,
                event_type=event_type,
                payload=payload,
                request_id=message.request_id or None,
            )
            session.add(event)

            if event_type == "status" and status_enum is not None:
                mapped = _map_status(status_enum)
                job.status = mapped
                if mapped == TrainingJobStatus.RUNNING and not job.started_at:
                    job.started_at = event_ts
                if mapped in (TrainingJobStatus.SUCCESS, TrainingJobStatus.FAILED, TrainingJobStatus.CANCELLED):
                    job.ended_at = event_ts
                if mapped == TrainingJobStatus.FAILED:
                    job.last_error = payload.get("reason") or payload.get("message")
            elif event_type == "metric":
                metrics = payload.get("metrics") or {}
                step = int(payload.get("step") or 0)
                epoch = payload.get("epoch")
                if isinstance(metrics, dict):
                    agg = dict(job.metrics or {})
                    for metric_name, metric_value in metrics.items():
                        try:
                            value = float(metric_value)
                        except Exception:
                            continue
                        agg[str(metric_name)] = value
                        existing_stmt = select(JobMetricPoint).where(
                            JobMetricPoint.job_id == job_id,
                            JobMetricPoint.step == step,
                            JobMetricPoint.metric_name == str(metric_name),
                        )
                        existing_point = (await session.exec(existing_stmt)).first()
                        if existing_point:
                            existing_point.metric_value = value
                            existing_point.epoch = int(epoch) if epoch is not None else None
                            existing_point.ts = event_ts
                            session.add(existing_point)
                        else:
                            metric_row = JobMetricPoint(
                                job_id=job_id,
                                step=step,
                                epoch=int(epoch) if epoch is not None else None,
                                metric_name=str(metric_name),
                                metric_value=value,
                                ts=event_ts,
                            )
                            session.add(metric_row)
                    job.metrics = agg
            elif event_type == "artifact":
                name = str(payload.get("name") or "")
                if name:
                    artifacts = dict(job.artifacts or {})
                    artifacts[name] = {
                        "kind": payload.get("kind", "artifact"),
                        "uri": payload.get("uri", ""),
                        "meta": payload.get("meta") or {},
                    }
                    job.artifacts = artifacts

            session.add(job)
            await session.commit()

    async def _persist_job_result(self, message: pb.JobResult) -> None:
        job_id_raw = message.job_id
        if not job_id_raw:
            return
        try:
            job_id = uuid.UUID(str(job_id_raw))
        except Exception:
            return

        metrics = {str(k): float(v) for k, v in message.metrics.items()}
        artifacts: dict[str, dict[str, object]] = {}
        for item in message.artifacts:
            name = str(item.name or "")
            if not name:
                continue
            artifacts[name] = {
                "kind": str(item.kind or "artifact"),
                "uri": str(item.uri or ""),
                "meta": runtime_codec.struct_to_dict(item.meta),
            }

        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return

            mapped = _map_status(int(message.status))
            job.status = mapped
            job.metrics = {**(job.metrics or {}), **metrics}
            job.artifacts = {**(job.artifacts or {}), **artifacts}
            job.ended_at = datetime.now(UTC)
            if mapped == TrainingJobStatus.FAILED:
                job.last_error = str(message.error_message or "runtime failed")

            for item in message.candidates:
                sample_id_raw = item.sample_id
                if not sample_id_raw:
                    continue
                try:
                    sample_id = uuid.UUID(str(sample_id_raw))
                    score = float(item.score or 0.0)
                except Exception:
                    continue
                reason = runtime_codec.struct_to_dict(item.reason)
                prediction_snapshot = {}
                extra = reason if isinstance(reason, dict) else {}
                if isinstance(extra, dict):
                    snap = extra.get("prediction_snapshot")
                    if isinstance(snap, dict):
                        prediction_snapshot = snap
                        extra = {k: v for k, v in extra.items() if k != "prediction_snapshot"}

                exists_stmt = select(JobSampleMetric).where(
                    JobSampleMetric.job_id == job_id,
                    JobSampleMetric.sample_id == sample_id,
                )
                existing = (await session.exec(exists_stmt)).first()
                if existing:
                    existing.score = score
                    existing.extra = extra
                    existing.prediction_snapshot = prediction_snapshot
                    session.add(existing)
                else:
                    session.add(
                        JobSampleMetric(
                            job_id=job_id,
                            sample_id=sample_id,
                            score=score,
                            extra=extra,
                            prediction_snapshot=prediction_snapshot,
                        )
                    )

            session.add(job)
            await session.commit()

    async def _build_data_response(self, message: pb.DataRequest) -> pb.RuntimeMessage:
        valid_query_types = {pb.LABELS, pb.SAMPLES, pb.ANNOTATIONS, pb.UNLABELED_SAMPLES}
        if int(message.query_type) not in valid_query_types:
            raise ValueError(f"invalid query_type: {int(message.query_type)}")
        query_type = runtime_codec.query_type_to_text(message.query_type)
        request_id = str(uuid.uuid4())
        limit = max(1, min(5000, int(message.limit or 1000)))
        offset = _parse_cursor(message.cursor or "")

        items: list[pb.DataItem] = []
        next_cursor: Optional[str] = None

        async with SessionLocal() as session:
            if query_type == "labels":
                project_id = _parse_uuid(message.project_id, "project_id")
                stmt = (
                    select(Label)
                    .where(Label.project_id == project_id)
                    .order_by(Label.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
                rows = list((await session.exec(stmt)).all())
                if len(rows) > limit:
                    rows = rows[:limit]
                    next_cursor = str(offset + limit)

                for item in rows:
                    items.append(
                        pb.DataItem(
                            label_item=pb.LabelItem(
                                id=str(item.id),
                                name=item.name or "",
                                color=item.color or "",
                            )
                        )
                    )

            elif query_type in {"samples", "unlabeled_samples"}:
                project_id = _parse_uuid(message.project_id, "project_id")
                commit_id = _parse_uuid(message.commit_id, "commit_id") if query_type == "unlabeled_samples" else None
                selection_exclude_open_batches = True
                loop_id_for_filter: uuid.UUID | None = None

                if query_type == "unlabeled_samples":
                    job_id_raw = str(message.job_id or "").strip()
                    if job_id_raw:
                        try:
                            job_id = uuid.UUID(job_id_raw)
                        except Exception:
                            job_id = None
                        if job_id:
                            job = await session.get(Job, job_id)
                            if job and job.loop_id:
                                loop_id_for_filter = job.loop_id
                                loop = await session.get(ALLoop, job.loop_id)
                                loop_config = normalize_loop_global_config(loop.global_config if loop else None)
                                selection_config = loop_config.get("selection")
                                if isinstance(selection_config, dict):
                                    selection_exclude_open_batches = bool(
                                        selection_config.get("exclude_open_batches", True)
                                    )

                ds_stmt = select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
                dataset_ids = [row[0] for row in (await session.exec(ds_stmt)).all()]
                if not dataset_ids:
                    return pb.RuntimeMessage(
                        data_response=pb.DataResponse(
                            request_id=request_id,
                            reply_to=message.request_id,
                            job_id=message.job_id,
                            query_type=runtime_codec.text_to_query_type(query_type),
                            items=[],
                            next_cursor="",
                        )
                    )

                sample_stmt = (
                    select(Sample, Asset)
                    .join(Asset, Sample.primary_asset_id == Asset.id, isouter=True)
                    .where(Sample.dataset_id.in_(dataset_ids))
                    .order_by(Sample.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
                if query_type == "unlabeled_samples":
                    assert commit_id is not None
                    annotated_subquery = select(CommitAnnotationMap.sample_id).where(
                        CommitAnnotationMap.commit_id == commit_id
                    )
                    sample_stmt = sample_stmt.where(Sample.id.not_in(annotated_subquery))
                    if selection_exclude_open_batches and loop_id_for_filter:
                        open_batch_sample_subquery = (
                            select(AnnotationBatchItem.sample_id)
                            .join(AnnotationBatch, AnnotationBatchItem.batch_id == AnnotationBatch.id)
                            .where(
                                AnnotationBatch.loop_id == loop_id_for_filter,
                                AnnotationBatch.status == AnnotationBatchStatus.OPEN,
                            )
                        )
                        sample_stmt = sample_stmt.where(Sample.id.not_in(open_batch_sample_subquery))

                rows = list((await session.exec(sample_stmt)).all())
                page = rows
                if len(page) > limit:
                    page = page[:limit]
                    next_cursor = str(offset + limit)

                for sample, asset in page:
                    asset_hash = ""
                    download_url = ""
                    width = 0
                    height = 0
                    if asset:
                        asset_hash = asset.hash or ""
                        meta = asset.meta_info or {}
                        width = int(meta.get("width") or 0)
                        height = int(meta.get("height") or 0)
                        try:
                            download_url = self.storage.get_presigned_url(asset.path)
                        except Exception:
                            download_url = ""

                    if not download_url:
                        continue

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

            elif query_type == "annotations":
                commit_id = _parse_uuid(message.commit_id, "commit_id")
                mapping_stmt = (
                    select(CommitAnnotationMap)
                    .where(CommitAnnotationMap.commit_id == commit_id)
                    .order_by(CommitAnnotationMap.sample_id)
                    .offset(offset)
                    .limit(limit + 1)
                )
                mappings = list((await session.exec(mapping_stmt)).all())
                if len(mappings) > limit:
                    mappings = mappings[:limit]
                    next_cursor = str(offset + limit)

                annotation_ids = [item.annotation_id for item in mappings]
                ann_stmt = select(Annotation).where(Annotation.id.in_(annotation_ids)) if annotation_ids else None
                ann_rows = list((await session.exec(ann_stmt)).all()) if ann_stmt is not None else []
                ann_map = {item.id: item for item in ann_rows}
                sample_ids = list({item.sample_id for item in mappings})
                sample_size_map: dict[uuid.UUID, tuple[int, int]] = {}
                if sample_ids:
                    sample_stmt = (
                        select(Sample, Asset)
                        .join(Asset, Sample.primary_asset_id == Asset.id, isouter=True)
                        .where(Sample.id.in_(sample_ids))
                    )
                    for sample, asset in (await session.exec(sample_stmt)).all():
                        width = 0
                        height = 0
                        if asset:
                            meta = asset.meta_info or {}
                            width = int(meta.get("width") or 0)
                            height = int(meta.get("height") or 0)
                        sample_size_map[sample.id] = (width, height)

                for mapping in mappings:
                    ann = ann_map.get(mapping.annotation_id)
                    if not ann:
                        continue
                    bbox_xywh = [0.0, 0.0, 0.0, 0.0]
                    obb = None
                    if ann.type == AnnotationType.RECT:
                        data = ann.data or {}
                        bbox_xywh = [
                            float(data.get("x", 0.0)),
                            float(data.get("y", 0.0)),
                            float(data.get("width", 0.0)),
                            float(data.get("height", 0.0)),
                        ]
                    elif ann.type == AnnotationType.OBB:
                        data = ann.data or {}
                        sample_width, sample_height = sample_size_map.get(ann.sample_id, (0, 0))
                        normalized_obb = _normalize_obb_payload(data)
                        if normalized_obb:
                            cx = float(normalized_obb["cx"])
                            cy = float(normalized_obb["cy"])
                            w = float(normalized_obb["w"])
                            h = float(normalized_obb["h"])
                            if int(sample_width or 0) > 0 and int(sample_height or 0) > 0:
                                cx *= float(sample_width)
                                cy *= float(sample_height)
                                w *= float(sample_width)
                                h *= float(sample_height)
                            bbox_xywh = [cx - w / 2, cy - h / 2, w, h]
                        obb = normalized_obb

                    item = pb.AnnotationItem(
                        id=str(ann.id),
                        sample_id=str(ann.sample_id),
                        category_id=str(ann.label_id),
                        bbox_xywh=bbox_xywh,
                        source=ann.source.value,
                        confidence=float(ann.confidence or 0.0),
                    )
                    if obb:
                        item.obb.CopyFrom(runtime_codec.dict_to_struct(obb))
                    items.append(pb.DataItem(annotation_item=item))

        return pb.RuntimeMessage(
            data_response=pb.DataResponse(
                request_id=request_id,
                reply_to=message.request_id,
                job_id=message.job_id,
                query_type=runtime_codec.text_to_query_type(query_type),
                items=items,
                next_cursor=next_cursor or "",
            )
        )

    async def _build_upload_ticket_response(self, message: pb.UploadTicketRequest) -> pb.RuntimeMessage:
        request_id = str(uuid.uuid4())
        job_id = str(message.job_id or "")
        if not job_id:
            raise ValueError("job_id is required")
        artifact_name = str(message.artifact_name or "artifact.bin")
        object_name = f"runtime/jobs/{job_id}/{artifact_name}"
        upload_url = self.storage.get_presigned_put_url(
            object_name=object_name,
            expires_delta=timedelta(hours=settings.RUNTIME_UPLOAD_URL_EXPIRE_HOURS),
        )
        storage_uri = f"s3://{settings.MINIO_BUCKET_NAME}/{object_name}"
        return pb.RuntimeMessage(
            upload_ticket_response=pb.UploadTicketResponse(
                request_id=request_id,
                reply_to=message.request_id,
                job_id=job_id,
                upload_url=upload_url,
                storage_uri=storage_uri,
                headers={},
            )
        )


class RuntimeGrpcServer:
    def __init__(self) -> None:
        self._server = grpc.aio.server()
        self._service = RuntimeControlService()
        self._watchdog_task: asyncio.Task | None = None
        pb_grpc.add_RuntimeControlServicer_to_server(self._service, self._server)

    async def _watchdog_loop(self) -> None:
        interval = max(1, settings.RUNTIME_DISPATCH_INTERVAL_SEC)
        while True:
            await asyncio.sleep(interval)
            try:
                await runtime_dispatcher.dispatch_pending_jobs()
            except Exception:
                logger.exception("Runtime watchdog loop failed")

    async def start(self) -> None:
        recovery = await runtime_dispatcher.recover_after_api_restart()
        logger.info("Runtime dispatcher recovery summary: %s", recovery)
        self._server.add_insecure_port(settings.RUNTIME_GRPC_BIND)
        await self._server.start()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("Runtime gRPC server listening on %s", settings.RUNTIME_GRPC_BIND)

    async def stop(self) -> None:
        if self._watchdog_task:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        await self._server.stop(grace=1)


_runtime_grpc_server: RuntimeGrpcServer | None = None


def get_runtime_grpc_server() -> RuntimeGrpcServer:
    global _runtime_grpc_server
    if _runtime_grpc_server is None:
        _runtime_grpc_server = RuntimeGrpcServer()
    return _runtime_grpc_server


class _LazyRuntimeGrpcServer:
    def __getattr__(self, item):
        return getattr(get_runtime_grpc_server(), item)


runtime_grpc_server = _LazyRuntimeGrpcServer()
