"""Runtime control gRPC server for Task-based runtime protocol."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

import grpc
from loguru import logger
from sqlmodel import select

from saki_api.core.config import settings
from saki_api.db.session import SessionLocal
from saki_api.grpc import runtime_codec
from saki_api.grpc.dispatcher import runtime_dispatcher
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.grpc_gen import runtime_control_pb2_grpc as pb_grpc
from saki_api.models.enums import JobStatusV2, JobTaskStatus
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import ProjectDataset
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_task import JobTask
from saki_api.models.l3.task_candidate_item import TaskCandidateItem
from saki_api.models.l3.task_event import TaskEvent
from saki_api.models.l3.task_metric_point import TaskMetricPoint
from saki_api.utils.storage import get_storage_provider


def _parse_uuid(raw: str | None, field_name: str) -> uuid.UUID:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return uuid.UUID(value)
    except Exception as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc


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


def _to_datetime_millis(ts: int) -> datetime:
    if int(ts) <= 0:
        return datetime.now(UTC)
    return datetime.fromtimestamp(float(ts) / 1000.0, tz=UTC)


@dataclass
class _RuntimeStreamState:
    outbox: asyncio.Queue[pb.RuntimeMessage]
    executor_id: str | None = None
    closed: bool = False


class RuntimeControlService(pb_grpc.RuntimeControlServicer):
    def __init__(self) -> None:
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    async def Stream(self, request_iterator, context):  # noqa: N802
        state = _RuntimeStreamState(outbox=asyncio.Queue())
        consumer = asyncio.create_task(self._consume_incoming(request_iterator=request_iterator, state=state))

        try:
            while True:
                message = await self._next_outgoing(state=state)
                if message is not None:
                    yield message
                    continue

                if consumer.done():
                    break
        finally:
            state.closed = True
            consumer.cancel()
            with contextlib.suppress(Exception):
                await consumer
            if state.executor_id:
                await runtime_dispatcher.unregister_executor(state.executor_id)

    async def _consume_incoming(self, *, request_iterator, state: _RuntimeStreamState) -> None:
        try:
            async for message in request_iterator:
                response = await self._handle_message(message=message, state=state)
                if response is not None:
                    await state.outbox.put(response)
        except grpc.RpcError as exc:
            logger.warning("runtime stream closed by grpc error={}", exc)
        except Exception:
            logger.exception("runtime stream incoming consume failed")

    async def _next_outgoing(self, *, state: _RuntimeStreamState) -> Optional[pb.RuntimeMessage]:
        if not state.outbox.empty():
            return state.outbox.get_nowait()

        if state.executor_id:
            control_message = await runtime_dispatcher.get_outgoing(state.executor_id, timeout=0.2)
            if control_message is not None:
                return control_message

        try:
            return await asyncio.wait_for(state.outbox.get(), timeout=0.2)
        except asyncio.TimeoutError:
            return None

    async def _handle_message(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> Optional[pb.RuntimeMessage]:
        payload_type = message.WhichOneof("payload")
        if payload_type == "register":
            return await self._handle_register(message.register, state)
        if payload_type == "heartbeat":
            return await self._handle_heartbeat(message.heartbeat, state)
        if payload_type == "ack":
            await runtime_dispatcher.handle_ack(message.ack)
            return None
        if payload_type == "task_event":
            await self._persist_task_event(message.task_event)
            return runtime_codec.build_ack_message(
                ack_for=str(message.task_event.request_id),
                status=pb.OK,
                ack_type=pb.ACK_TYPE_REQUEST,
                ack_reason=pb.ACK_REASON_ACCEPTED,
                detail="task_event persisted",
            )
        if payload_type == "task_result":
            await self._persist_task_result(message.task_result)
            return runtime_codec.build_ack_message(
                ack_for=str(message.task_result.request_id),
                status=pb.OK,
                ack_type=pb.ACK_TYPE_REQUEST,
                ack_reason=pb.ACK_REASON_ACCEPTED,
                detail="task_result persisted",
            )
        if payload_type == "data_request":
            return await self._handle_data_request(message.data_request)
        if payload_type == "upload_ticket_request":
            return await self._handle_upload_ticket_request(message.upload_ticket_request)
        if payload_type == "error":
            logger.warning(
                "runtime error from executor request_id={} code={} message={} reason={}",
                message.error.request_id,
                message.error.code,
                message.error.message,
                message.error.reason,
            )
            return None

        return runtime_codec.build_error_message(
            code="unknown_payload",
            message=f"unsupported payload type: {payload_type}",
            reason="unsupported_payload",
        )

    async def _handle_register(self, message: pb.Register, state: _RuntimeStreamState) -> pb.RuntimeMessage:
        payload = runtime_codec.parse_register(message)
        executor_id = payload["executor_id"]
        if not executor_id:
            return runtime_codec.build_error_message(
                code="invalid_register",
                message="executor_id is required",
                reply_to=str(message.request_id),
                reason="executor_id_required",
            )

        await runtime_dispatcher.register_executor(
            executor_id=executor_id,
            version=payload["version"],
            plugin_payloads=payload["plugins"],
            resources=payload["resources"],
        )
        state.executor_id = executor_id

        return runtime_codec.build_ack_message(
            ack_for=str(message.request_id),
            status=pb.OK,
            ack_type=pb.ACK_TYPE_REGISTER,
            ack_reason=pb.ACK_REASON_REGISTERED,
            detail="registered",
        )

    async def _handle_heartbeat(self, message: pb.Heartbeat, state: _RuntimeStreamState) -> pb.RuntimeMessage:
        payload = runtime_codec.parse_heartbeat(message)
        executor_id = payload["executor_id"]
        if not executor_id:
            return runtime_codec.build_error_message(
                code="invalid_heartbeat",
                message="executor_id is required",
                reply_to=str(message.request_id),
                reason="executor_id_required",
            )

        if state.executor_id and state.executor_id != executor_id:
            return runtime_codec.build_error_message(
                code="executor_id_conflict",
                message="heartbeat executor_id does not match stream register executor_id",
                reply_to=str(message.request_id),
                reason="executor_id_conflict",
            )

        state.executor_id = executor_id
        await runtime_dispatcher.handle_heartbeat(
            executor_id=executor_id,
            busy=bool(payload["busy"]),
            current_task_id=payload["current_task_id"],
            resources=payload["resources"],
        )

        return runtime_codec.build_ack_message(
            ack_for=str(message.request_id),
            status=pb.OK,
            ack_type=pb.ACK_TYPE_REQUEST,
            ack_reason=pb.ACK_REASON_ACCEPTED,
            detail="heartbeat accepted",
        )

    async def _handle_data_request(self, message: pb.DataRequest) -> pb.RuntimeMessage:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        query_type = int(message.query_type)
        project_id_raw = str(message.project_id or "")
        commit_id_raw = str(message.commit_id or "")
        limit = max(1, min(int(message.limit or 1000), 5000))
        offset = self._parse_cursor(message.cursor)

        if not request_id or not task_id:
            return runtime_codec.build_error_message(
                code="invalid_data_request",
                message="request_id and task_id are required",
                reply_to=request_id,
                task_id=task_id,
                query_type=query_type,
                reason="missing_required_field",
            )

        try:
            project_id = _parse_uuid(project_id_raw, "project_id")
            commit_id = _parse_uuid(commit_id_raw, "commit_id")
        except ValueError as exc:
            return runtime_codec.build_error_message(
                code="invalid_data_request",
                message=str(exc),
                reply_to=request_id,
                task_id=task_id,
                query_type=query_type,
                reason="invalid_uuid",
            )

        try:
            items, next_cursor = await self._query_data_items(
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            logger.exception("data request failed request_id={} task_id={} error={}", request_id, task_id, exc)
            return runtime_codec.build_error_message(
                code="data_query_failed",
                message="data query failed",
                reply_to=request_id,
                task_id=task_id,
                query_type=query_type,
                reason=str(exc),
            )

        return pb.RuntimeMessage(
            data_response=pb.DataResponse(
                request_id=str(uuid.uuid4()),
                reply_to=request_id,
                task_id=task_id,
                query_type=query_type,
                items=items,
                next_cursor=next_cursor or "",
            )
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
        async with SessionLocal() as session:
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
                                obb=runtime_codec.dict_to_struct(payload.get("obb") if isinstance(payload.get("obb"), dict) else {}),
                                source=str(ann.source.value if hasattr(ann.source, "value") else ann.source),
                                confidence=float(ann.confidence or 0.0),
                            )
                        )
                    )
                return items, next_cursor

            raise RuntimeError(f"unsupported query_type={query_type}")

    async def _handle_upload_ticket_request(self, message: pb.UploadTicketRequest) -> pb.RuntimeMessage:
        request_id = str(message.request_id or "")
        task_id = str(message.task_id or "")
        artifact_name = str(message.artifact_name or "").strip()
        content_type = str(message.content_type or "application/octet-stream")

        if not request_id or not task_id or not artifact_name:
            return runtime_codec.build_error_message(
                code="invalid_upload_ticket_request",
                message="request_id/task_id/artifact_name are required",
                reply_to=request_id,
                task_id=task_id,
                reason="missing_required_field",
            )

        object_name = f"runtime/tasks/{task_id}/{artifact_name}"
        try:
            upload_url = self.storage.get_presigned_put_url(
                object_name=object_name,
                expires_delta=timedelta(hours=settings.RUNTIME_UPLOAD_URL_EXPIRE_HOURS),
            )
        except Exception as exc:
            logger.exception("failed to issue upload ticket task_id={} error={}", task_id, exc)
            return runtime_codec.build_error_message(
                code="upload_ticket_failed",
                message="failed to issue upload ticket",
                reply_to=request_id,
                task_id=task_id,
                reason=str(exc),
            )

        storage_uri = f"s3://{settings.MINIO_BUCKET_NAME}/{object_name}"
        return pb.RuntimeMessage(
            upload_ticket_response=pb.UploadTicketResponse(
                request_id=str(uuid.uuid4()),
                reply_to=request_id,
                task_id=task_id,
                upload_url=upload_url,
                storage_uri=storage_uri,
                headers={"Content-Type": content_type},
            )
        )

    async def _persist_task_event(self, message: pb.TaskEvent) -> None:
        task_id = _parse_uuid(message.task_id, "task_id")
        event_type, payload, status_enum = runtime_codec.decode_task_event(message)

        async with SessionLocal() as session:
            task = await session.get(JobTask, task_id)
            if not task:
                raise ValueError(f"task not found: {task_id}")

            exists = (
                await session.exec(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task_id, TaskEvent.seq == int(message.seq))
                    .limit(1)
                )
            ).first()
            if exists:
                return

            session.add(
                TaskEvent(
                    task_id=task_id,
                    seq=int(message.seq),
                    ts=_to_datetime_millis(int(message.ts)),
                    event_type=event_type,
                    payload=payload,
                    request_id=str(message.request_id or "") or None,
                )
            )

            if event_type == "status" and status_enum is not None:
                mapped = _status_from_pb(status_enum)
                task.status = mapped
                if mapped == JobTaskStatus.RUNNING and not task.started_at:
                    task.started_at = datetime.now(UTC)
                if mapped in {JobTaskStatus.SUCCEEDED, JobTaskStatus.FAILED, JobTaskStatus.CANCELLED, JobTaskStatus.SKIPPED}:
                    task.ended_at = datetime.now(UTC)
                    task.last_error = str(payload.get("reason") or "") or None
                session.add(task)

            if event_type == "metric":
                metrics = payload.get("metrics") or {}
                for metric_name, metric_value in metrics.items():
                    session.add(
                        TaskMetricPoint(
                            task_id=task.id,
                            step=int(payload.get("step") or 0),
                            epoch=int(payload.get("epoch") or 0) if payload.get("epoch") is not None else None,
                            metric_name=str(metric_name),
                            metric_value=float(metric_value),
                            ts=_to_datetime_millis(int(message.ts)),
                        )
                    )

            if event_type == "artifact":
                artifacts = dict(task.artifacts or {})
                name = str(payload.get("name") or "")
                if name:
                    artifacts[name] = {
                        "kind": str(payload.get("kind") or "artifact"),
                        "uri": str(payload.get("uri") or ""),
                        "meta": payload.get("meta") or {},
                    }
                    task.artifacts = artifacts
                    session.add(task)

            await self._recompute_job_summary(session=session, job_id=task.job_id)
            await session.commit()

    async def _persist_task_result(self, message: pb.TaskResult) -> None:
        task_id = _parse_uuid(message.task_id, "task_id")

        async with SessionLocal() as session:
            task = await session.get(JobTask, task_id)
            if not task:
                raise ValueError(f"task not found: {task_id}")

            mapped = _status_from_pb(int(message.status))
            task.status = mapped
            task.metrics = {str(k): float(v) for k, v in message.metrics.items()}
            artifacts: dict[str, dict[str, object]] = {}
            for item in message.artifacts:
                artifacts[str(item.name)] = {
                    "kind": str(item.kind or "artifact"),
                    "uri": str(item.uri or ""),
                    "meta": runtime_codec.struct_to_dict(item.meta),
                }
            task.artifacts = artifacts
            task.last_error = str(message.error_message or "") or None
            task.ended_at = datetime.now(UTC)
            if not task.started_at:
                task.started_at = datetime.now(UTC)
            session.add(task)

            existing_candidates = list(
                (
                    await session.exec(
                        select(TaskCandidateItem).where(TaskCandidateItem.task_id == task.id)
                    )
                ).all()
            )
            for item in existing_candidates:
                await session.delete(item)

            for idx, candidate in enumerate(message.candidates, start=1):
                sample_id_raw = str(candidate.sample_id or "").strip()
                if not sample_id_raw:
                    continue
                try:
                    sample_id = uuid.UUID(sample_id_raw)
                except Exception:
                    continue
                session.add(
                    TaskCandidateItem(
                        task_id=task.id,
                        sample_id=sample_id,
                        rank=idx,
                        score=float(candidate.score or 0.0),
                        reason=runtime_codec.struct_to_dict(candidate.reason),
                        prediction_snapshot={},
                    )
                )

            for metric_name, metric_value in task.metrics.items():
                session.add(
                    TaskMetricPoint(
                        task_id=task.id,
                        step=0,
                        epoch=None,
                        metric_name=str(metric_name),
                        metric_value=float(metric_value),
                        ts=datetime.now(UTC),
                    )
                )

            await self._recompute_job_summary(session=session, job_id=task.job_id)
            await session.commit()

    async def _recompute_job_summary(self, *, session, job_id: uuid.UUID) -> None:
        job = await session.get(Job, job_id)
        if not job:
            return

        rows = await session.exec(
            select(JobTask).where(JobTask.job_id == job_id).order_by(JobTask.task_index.asc())
        )
        tasks = list(rows.all())
        if not tasks:
            job.summary_status = JobStatusV2.JOB_PENDING
            job.task_counts = {}
            session.add(job)
            return

        counts: dict[str, int] = {}
        for task in tasks:
            key = task.status.value
            counts[key] = counts.get(key, 0) + 1

        all_terminal = all(
            task.status in {JobTaskStatus.SUCCEEDED, JobTaskStatus.FAILED, JobTaskStatus.CANCELLED, JobTaskStatus.SKIPPED}
            for task in tasks
        )
        any_running = any(task.status in {JobTaskStatus.RUNNING, JobTaskStatus.DISPATCHING, JobTaskStatus.RETRYING} for task in tasks)
        any_failed = any(task.status == JobTaskStatus.FAILED for task in tasks)
        any_cancelled = any(task.status == JobTaskStatus.CANCELLED for task in tasks)
        all_succeeded = all(task.status in {JobTaskStatus.SUCCEEDED, JobTaskStatus.SKIPPED} for task in tasks)

        if any_running:
            summary = JobStatusV2.JOB_RUNNING
        elif all_terminal and all_succeeded:
            summary = JobStatusV2.JOB_SUCCEEDED
        elif all_terminal and any_cancelled and not any_failed:
            summary = JobStatusV2.JOB_CANCELLED
        elif all_terminal and any_failed and all(task.status == JobTaskStatus.FAILED for task in tasks):
            summary = JobStatusV2.JOB_FAILED
        elif all_terminal and (any_failed or any_cancelled):
            summary = JobStatusV2.JOB_PARTIAL_FAILED
        else:
            summary = JobStatusV2.JOB_PENDING

        job.summary_status = summary
        job.task_counts = counts
        if summary == JobStatusV2.JOB_RUNNING and not job.started_at:
            job.started_at = datetime.now(UTC)
        if summary in {JobStatusV2.JOB_SUCCEEDED, JobStatusV2.JOB_FAILED, JobStatusV2.JOB_PARTIAL_FAILED, JobStatusV2.JOB_CANCELLED}:
            job.ended_at = datetime.now(UTC)
        if tasks:
            last_task = tasks[-1]
            job.final_metrics = dict(last_task.metrics or {})
            job.final_artifacts = dict(last_task.artifacts or {})
            job.result_commit_id = last_task.result_commit_id
            if last_task.last_error:
                job.last_error = last_task.last_error
        session.add(job)

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


class RuntimeGrpcServer:
    def __init__(self) -> None:
        self._server: grpc.aio.Server | None = None
        self._service = RuntimeControlService()

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = grpc.aio.server()
        pb_grpc.add_RuntimeControlServicer_to_server(self._service, self._server)
        self._server.add_insecure_port(settings.RUNTIME_GRPC_BIND)
        await self._server.start()
        logger.info("runtime grpc server started bind={}", settings.RUNTIME_GRPC_BIND)

    async def stop(self) -> None:
        if self._server is None:
            return
        await self._server.stop(grace=2)
        await self._server.wait_for_termination()
        self._server = None
        logger.info("runtime grpc server stopped")


runtime_grpc_server = RuntimeGrpcServer()
