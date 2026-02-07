"""
Runtime control gRPC server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

import grpc
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_control_pb2_grpc as pb_grpc
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


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except Exception:
        return 0


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


class RuntimeControlService(pb_grpc.RuntimeControlServicer):
    def __init__(self) -> None:
        self.storage = get_storage_provider()

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

        async def _reader() -> None:
            nonlocal executor_id
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
                        await self._persist_job_event(message.job_event)
                        continue

                    if payload_type == "job_result":
                        await self._persist_job_result(message.job_result)
                        if executor_id:
                            await runtime_dispatcher.mark_executor_idle(
                                executor_id=executor_id,
                                job_id=message.job_result.job_id,
                            )
                        continue

                    if payload_type == "data_request":
                        request = message.data_request
                        try:
                            response = await self._build_data_response(request)
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
                        continue

                    if payload_type == "upload_ticket_request":
                        request = message.upload_ticket_request
                        try:
                            response = await self._build_upload_ticket_response(request)
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
                        continue

                    if payload_type == "ack":
                        ack = message.ack
                        await runtime_dispatcher.handle_ack(
                            ack_for=str(ack.ack_for or ""),
                            status=int(ack.status),
                            message=ack.message or None,
                        )
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
                payload = await outbox.get()
                yield payload
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

        event_ts = datetime.utcfromtimestamp(int(message.ts or int(datetime.utcnow().timestamp())))
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
            job.ended_at = datetime.utcnow()
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

    async def _build_data_response(self, message: pb.DataRequest) -> pb.RuntimeMessage:
        query_type = runtime_codec.query_type_to_text(message.query_type)
        request_id = str(uuid.uuid4())
        limit = max(1, min(5000, int(message.limit or 1000)))
        offset = _parse_cursor(message.cursor or "")

        items: list[pb.DataItem] = []
        next_cursor: Optional[str] = None

        async with SessionLocal() as session:
            if query_type == "labels":
                project_id = uuid.UUID(str(message.project_id))
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
                project_id = uuid.UUID(str(message.project_id))
                commit_id = uuid.UUID(str(message.commit_id))

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
                    asset_hash = ""
                    download_url = ""
                    width = 0
                    height = 0
                    if sample.primary_asset_id:
                        asset = await session.get(Asset, sample.primary_asset_id)
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
                commit_id = uuid.UUID(str(message.commit_id))
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
