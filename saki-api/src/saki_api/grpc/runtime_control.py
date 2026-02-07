"""
Runtime control gRPC server.

Implementation note:
- Uses JSON payload over a gRPC bidirectional stream method path.
- `proto/runtime_control.proto` is the contract source; generated stubs can be added later.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import grpc
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.models.enums import AnnotationType, TrainingJobStatus
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import ProjectDataset
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.utils.storage import get_storage_provider

logger = logging.getLogger(__name__)

_SERVICE_NAME = "saki.runtime.v1.RuntimeControl"
_METHOD_NAME = "Stream"


def _decode(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except Exception:
        return 0


def _map_status(status: str) -> TrainingJobStatus:
    mapping = {
        "created": TrainingJobStatus.PENDING,
        "queued": TrainingJobStatus.PENDING,
        "running": TrainingJobStatus.RUNNING,
        "stopping": TrainingJobStatus.RUNNING,
        "stopped": TrainingJobStatus.CANCELLED,
        "succeeded": TrainingJobStatus.SUCCESS,
        "failed": TrainingJobStatus.FAILED,
        # direct DB enums compatibility
        "pending": TrainingJobStatus.PENDING,
        "success": TrainingJobStatus.SUCCESS,
        "cancelled": TrainingJobStatus.CANCELLED,
    }
    return mapping.get((status or "").lower(), TrainingJobStatus.PENDING)


class RuntimeControlService:
    def __init__(self) -> None:
        self.storage = get_storage_provider()

    async def stream(self, request_iterator, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("x-internal-token") != settings.INTERNAL_TOKEN:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")

        outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        executor_id: Optional[str] = None

        async def _reader() -> None:
            nonlocal executor_id
            async for raw in request_iterator:
                try:
                    message = _decode(raw)
                    msg_type = message.get("type")
                    if msg_type == "register":
                        executor_id = str(message.get("executor_id") or "")
                        if not executor_id:
                            await outbox.put(
                                {
                                    "type": "error",
                                    "request_id": str(uuid.uuid4()),
                                    "code": "INVALID_ARGUMENT",
                                    "message": "executor_id is required",
                                }
                            )
                            continue

                        plugin_ids = {
                            str(item.get("plugin_id"))
                            for item in (message.get("plugins") or [])
                            if item.get("plugin_id")
                        }
                        resources = message.get("resources") or {}
                        try:
                            await runtime_dispatcher.register(
                                executor_id=executor_id,
                                queue=outbox,
                                version=str(message.get("version") or ""),
                                plugin_ids=plugin_ids,
                                resources=resources,
                            )
                        except PermissionError as exc:
                            await outbox.put(
                                {
                                    "type": "error",
                                    "request_id": str(uuid.uuid4()),
                                    "code": "FORBIDDEN",
                                    "message": str(exc),
                                }
                            )
                            continue
                        except Exception as exc:
                            await outbox.put(
                                {
                                    "type": "error",
                                    "request_id": str(uuid.uuid4()),
                                    "code": "INTERNAL",
                                    "message": f"register failed: {exc}",
                                }
                            )
                            continue
                        await outbox.put(
                            {
                                "type": "ack",
                                "request_id": str(uuid.uuid4()),
                                "ack_for": message.get("request_id", ""),
                                "status": "ok",
                                "message": "registered",
                            }
                        )
                    elif msg_type == "heartbeat":
                        if not executor_id:
                            continue
                        await runtime_dispatcher.heartbeat(
                            executor_id=executor_id,
                            busy=bool(message.get("busy", False)),
                            current_job_id=message.get("current_job_id"),
                            resources=message.get("resources") or {},
                        )
                    elif msg_type == "job_event":
                        await self._persist_job_event(message)
                    elif msg_type == "job_result":
                        await self._persist_job_result(message)
                        if executor_id:
                            await runtime_dispatcher.mark_executor_idle(
                                executor_id=executor_id,
                                job_id=message.get("job_id"),
                            )
                    elif msg_type == "data_request":
                        try:
                            response = await self._build_data_response(message)
                        except Exception as exc:
                            response = {
                                "type": "data_response",
                                "request_id": str(uuid.uuid4()),
                                "reply_to": message.get("request_id"),
                                "job_id": message.get("job_id"),
                                "query_type": message.get("query_type"),
                                "items": [],
                                "next_cursor": None,
                                "error": str(exc),
                            }
                        await outbox.put(response)
                    elif msg_type == "upload_ticket_request":
                        try:
                            response = await self._build_upload_ticket_response(message)
                        except Exception as exc:
                            response = {
                                "type": "upload_ticket_response",
                                "request_id": str(uuid.uuid4()),
                                "reply_to": message.get("request_id"),
                                "job_id": message.get("job_id"),
                                "upload_url": "",
                                "storage_uri": "",
                                "headers": {},
                                "error": str(exc),
                            }
                        await outbox.put(response)
                    elif msg_type == "ack":
                        await runtime_dispatcher.handle_ack(
                            ack_for=str(message.get("ack_for") or ""),
                            status=str(message.get("status") or ""),
                            message=message.get("message"),
                        )
                    elif msg_type == "error":
                        logger.error("Executor error message: %s", message)
                    else:
                        logger.warning("Unknown runtime message type: %s", msg_type)
                except Exception:
                    logger.exception("Failed to process runtime message")

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                payload = await outbox.get()
                yield _encode(payload)
        finally:
            reader_task.cancel()
            if executor_id:
                await runtime_dispatcher.unregister(executor_id)

    async def _persist_job_event(self, message: dict[str, Any]) -> None:
        job_id_raw = message.get("job_id")
        if not job_id_raw:
            return
        try:
            job_id = uuid.UUID(str(job_id_raw))
        except Exception:
            return

        seq = int(message.get("seq") or 0)
        if seq <= 0:
            return

        event_ts = datetime.utcfromtimestamp(int(message.get("ts") or int(datetime.utcnow().timestamp())))
        event_type = str(message.get("event_type") or "")
        payload = message.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw": payload}

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
                request_id=message.get("request_id"),
            )
            session.add(event)

            if event_type == "status":
                status_text = str(payload.get("status") or "")
                mapped = _map_status(status_text)
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

    async def _persist_job_result(self, message: dict[str, Any]) -> None:
        job_id_raw = message.get("job_id")
        if not job_id_raw:
            return
        try:
            job_id = uuid.UUID(str(job_id_raw))
        except Exception:
            return

        status_text = str(message.get("status") or "")
        metrics = message.get("metrics") or {}
        artifacts = message.get("artifacts") or {}
        candidates = message.get("candidates") or []
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except Exception:
                metrics = {}
        if isinstance(artifacts, str):
            try:
                artifacts = json.loads(artifacts)
            except Exception:
                artifacts = {}

        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return

            mapped = _map_status(status_text)
            job.status = mapped
            job.metrics = {**(job.metrics or {}), **(metrics if isinstance(metrics, dict) else {})}
            job.artifacts = {**(job.artifacts or {}), **(artifacts if isinstance(artifacts, dict) else {})}
            job.ended_at = datetime.utcnow()
            if mapped == TrainingJobStatus.FAILED:
                job.last_error = str(message.get("error_message") or "runtime failed")

            for item in candidates:
                sample_id_raw = item.get("sample_id")
                if not sample_id_raw:
                    continue
                try:
                    sample_id = uuid.UUID(str(sample_id_raw))
                    score = float(item.get("score") or 0.0)
                except Exception:
                    continue
                reason = item.get("reason") or {}
                if isinstance(reason, str):
                    try:
                        reason = json.loads(reason)
                    except Exception:
                        reason = {"raw": reason}

                exists_stmt = select(JobSampleMetric).where(
                    JobSampleMetric.job_id == job_id,
                    JobSampleMetric.sample_id == sample_id,
                )
                existing = (await session.exec(exists_stmt)).first()
                if existing:
                    existing.score = score
                    existing.extra = reason if isinstance(reason, dict) else {}
                    session.add(existing)
                else:
                    session.add(
                        JobSampleMetric(
                            job_id=job_id,
                            sample_id=sample_id,
                            score=score,
                            extra=reason if isinstance(reason, dict) else {},
                            prediction_snapshot={},
                        )
                    )

            session.add(job)
            await session.commit()

    async def _build_data_response(self, message: dict[str, Any]) -> dict[str, Any]:
        query_type = str(message.get("query_type") or "")
        request_id = str(uuid.uuid4())
        limit = max(1, min(5000, int(message.get("limit") or 1000)))
        cursor = str(message.get("cursor") or "")
        offset = _parse_cursor(cursor)

        items: list[dict[str, Any]] = []
        next_cursor: Optional[str] = None

        async with SessionLocal() as session:
            if query_type == "labels":
                project_id = uuid.UUID(str(message.get("project_id")))
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
                items = [{"id": str(item.id), "name": item.name, "color": item.color} for item in rows]

            elif query_type in {"samples", "unlabeled_samples"}:
                project_id = uuid.UUID(str(message.get("project_id")))
                commit_id = uuid.UUID(str(message.get("commit_id")))

                ds_stmt = select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
                dataset_ids = [row[0] for row in (await session.exec(ds_stmt)).all()]

                all_samples_stmt = (
                    select(Sample)
                    .where(Sample.dataset_id.in_(dataset_ids))
                    .order_by(Sample.id)
                )
                sample_rows = list((await session.exec(all_samples_stmt)).all())

                if query_type == "unlabeled_samples":
                    ann_stmt = select(CommitAnnotationMap.sample_id).where(CommitAnnotationMap.commit_id == commit_id)
                    annotated_ids = {row[0] for row in (await session.exec(ann_stmt)).all()}
                    sample_rows = [item for item in sample_rows if item.id not in annotated_ids]

                page = sample_rows[offset: offset + limit + 1]
                if len(page) > limit:
                    page = page[:limit]
                    next_cursor = str(offset + limit)

                for sample in page:
                    asset_hash = None
                    download_url = None
                    width = 0
                    height = 0
                    if sample.primary_asset_id:
                        asset = await session.get(Asset, sample.primary_asset_id)
                        if asset:
                            asset_hash = asset.hash
                            meta = asset.meta_info or {}
                            width = int(meta.get("width") or 0)
                            height = int(meta.get("height") or 0)
                            try:
                                download_url = self.storage.get_presigned_url(asset.path)
                            except Exception:
                                download_url = None
                    if not download_url:
                        continue
                    items.append(
                        {
                            "id": str(sample.id),
                            "asset_hash": asset_hash,
                            "download_url": download_url,
                            "width": width,
                            "height": height,
                            "meta": sample.meta_info or {},
                        }
                    )

            elif query_type == "annotations":
                commit_id = uuid.UUID(str(message.get("commit_id")))
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
                        cx = float(data.get("cx", 0.0))
                        cy = float(data.get("cy", 0.0))
                        w = float(data.get("width", 0.0))
                        h = float(data.get("height", 0.0))
                        bbox_xywh = [cx - w / 2, cy - h / 2, w, h]
                        obb = data

                    items.append(
                        {
                            "id": str(ann.id),
                            "sample_id": str(ann.sample_id),
                            "category_id": str(ann.label_id),
                            "bbox_xywh": bbox_xywh,
                            "obb": obb,
                            "source": ann.source.value,
                            "confidence": ann.confidence,
                        }
                    )

        return {
            "type": "data_response",
            "request_id": request_id,
            "reply_to": message.get("request_id"),
            "job_id": message.get("job_id"),
            "query_type": query_type,
            "items": items,
            "next_cursor": next_cursor,
        }

    async def _build_upload_ticket_response(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        job_id = str(message.get("job_id") or "")
        artifact_name = str(message.get("artifact_name") or "artifact.bin")
        object_name = f"runtime/jobs/{job_id}/{artifact_name}"
        upload_url = self.storage.get_presigned_put_url(
            object_name=object_name,
            expires_delta=timedelta(hours=settings.RUNTIME_UPLOAD_URL_EXPIRE_HOURS),
        )
        storage_uri = f"s3://{settings.MINIO_BUCKET_NAME}/{object_name}"
        return {
            "type": "upload_ticket_response",
            "request_id": request_id,
            "reply_to": message.get("request_id"),
            "job_id": job_id,
            "upload_url": upload_url,
            "storage_uri": storage_uri,
            "headers": {},
        }


class RuntimeGrpcServer:
    def __init__(self) -> None:
        self._server = grpc.aio.server()
        self._service = RuntimeControlService()
        self._watchdog_task: asyncio.Task | None = None
        handler = grpc.stream_stream_rpc_method_handler(
            self._service.stream,
            request_deserializer=lambda x: x,
            response_serializer=lambda x: x,
        )
        generic_handler = grpc.method_handlers_generic_handler(
            _SERVICE_NAME,
            {_METHOD_NAME: handler},
        )
        self._server.add_generic_rpc_handlers((generic_handler,))

    async def _watchdog_loop(self) -> None:
        interval = max(1, settings.RUNTIME_DISPATCH_INTERVAL_SEC)
        while True:
            await asyncio.sleep(interval)
            try:
                await runtime_dispatcher.dispatch_pending_jobs()
            except Exception:
                logger.exception("Runtime watchdog loop failed")

    async def start(self) -> None:
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


runtime_grpc_server = RuntimeGrpcServer()
