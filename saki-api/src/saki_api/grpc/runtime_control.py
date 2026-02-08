"""
Runtime control gRPC server.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from dataclasses import dataclass
from loguru import logger
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

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


def _is_downloadable_artifact_uri(uri: str | None) -> bool:
    raw = str(uri or "").strip()
    return raw.startswith("s3://") or raw.startswith("http://") or raw.startswith("https://")


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
        pb.PARTIAL_FAILED: TrainingJobStatus.PARTIAL_FAILED,
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


@dataclass
class _RuntimeStreamState:
    outbox: asyncio.Queue[pb.RuntimeMessage]
    dedup_cache: _RequestDedupCache
    executor_id: str | None = None
    close_stream_after_flush: bool = False


class RuntimeControlService(pb_grpc.RuntimeControlServicer):
    def __init__(self) -> None:
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    @staticmethod
    def _extract_scalar_values(rows: list[object]) -> list[object]:
        values: list[object] = []
        for row in rows:
            if isinstance(row, (tuple, list)):
                if row:
                    values.append(row[0])
                continue
            values.append(row)
        return values

    @staticmethod
    def _paginate_rows(rows: list[object], *, limit: int, offset: int) -> tuple[list[object], str | None]:
        page = rows
        next_cursor: str | None = None
        if len(page) > limit:
            page = page[:limit]
            next_cursor = str(offset + limit)
        return page, next_cursor

    async def _query_labels_items(
        self,
        *,
        session,
        project_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[pb.DataItem], str | None]:
        stmt = (
            select(Label)
            .where(Label.project_id == project_id)
            .order_by(Label.id)
            .offset(offset)
            .limit(limit + 1)
        )
        rows = list((await session.exec(stmt)).all())
        page, next_cursor = self._paginate_rows(rows, limit=limit, offset=offset)

        items: list[pb.DataItem] = []
        for item in page:
            items.append(
                pb.DataItem(
                    label_item=pb.LabelItem(
                        id=str(item.id),
                        name=item.name or "",
                        color=item.color or "",
                    )
                )
            )
        return items, next_cursor

    async def _resolve_unlabeled_selection_filter(
        self,
        *,
        session,
        query_type: str,
        job_id_raw: str,
    ) -> tuple[bool, uuid.UUID | None]:
        selection_exclude_open_batches = True
        loop_id_for_filter: uuid.UUID | None = None
        if query_type != "unlabeled_samples":
            return selection_exclude_open_batches, loop_id_for_filter

        job_id_value = str(job_id_raw or "").strip()
        if not job_id_value:
            return selection_exclude_open_batches, loop_id_for_filter

        try:
            job_id = uuid.UUID(job_id_value)
        except Exception:
            return selection_exclude_open_batches, loop_id_for_filter

        job = await session.get(Job, job_id)
        if not job or not job.loop_id:
            return selection_exclude_open_batches, loop_id_for_filter

        loop_id_for_filter = job.loop_id
        loop = await session.get(ALLoop, job.loop_id)
        loop_config = normalize_loop_global_config(loop.global_config if loop else None)
        selection_config = loop_config.get("selection")
        if isinstance(selection_config, dict):
            selection_exclude_open_batches = bool(selection_config.get("exclude_open_batches", True))
        return selection_exclude_open_batches, loop_id_for_filter

    async def _list_project_dataset_ids(
        self,
        *,
        session,
        project_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        ds_stmt = select(ProjectDataset.dataset_id).where(ProjectDataset.project_id == project_id)
        dataset_ids_raw = list((await session.exec(ds_stmt)).all())
        dataset_ids: list[uuid.UUID] = []
        for value in self._extract_scalar_values(dataset_ids_raw):
            if not value:
                continue
            try:
                dataset_ids.append(uuid.UUID(str(value)))
            except Exception as exc:
                raise ValueError(f"invalid dataset_id in project {project_id}: {value}") from exc
        return dataset_ids

    def _build_samples_query(
        self,
        *,
        query_type: str,
        dataset_ids: list[uuid.UUID],
        limit: int,
        offset: int,
        commit_id: uuid.UUID | None,
        selection_exclude_open_batches: bool,
        loop_id_for_filter: uuid.UUID | None,
    ):
        sample_stmt = (
            select(Sample, Asset)
            .join(Asset, Sample.primary_asset_id == Asset.id, isouter=True)
            .where(Sample.dataset_id.in_(dataset_ids))
            .order_by(Sample.id)
            .offset(offset)
            .limit(limit + 1)
        )
        if query_type != "unlabeled_samples":
            return sample_stmt
        if commit_id is None:
            raise ValueError("commit_id is required")

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
        return sample_stmt

    def _build_sample_data_item(self, *, sample: Sample, asset: Asset | None) -> pb.DataItem | None:
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
            return None

        return pb.DataItem(
            sample_item=pb.SampleItem(
                id=str(sample.id),
                asset_hash=asset_hash,
                download_url=download_url,
                width=width,
                height=height,
                meta=runtime_codec.dict_to_struct(sample.meta_info or {}),
            )
        )

    async def _query_samples_items(
        self,
        *,
        session,
        query_type: str,
        project_id: uuid.UUID,
        commit_id: uuid.UUID | None,
        job_id_raw: str,
        limit: int,
        offset: int,
    ) -> tuple[list[pb.DataItem], str | None]:
        selection_exclude_open_batches, loop_id_for_filter = await self._resolve_unlabeled_selection_filter(
            session=session,
            query_type=query_type,
            job_id_raw=job_id_raw,
        )
        dataset_ids = await self._list_project_dataset_ids(session=session, project_id=project_id)
        if not dataset_ids:
            return [], None

        sample_stmt = self._build_samples_query(
            query_type=query_type,
            dataset_ids=dataset_ids,
            limit=limit,
            offset=offset,
            commit_id=commit_id,
            selection_exclude_open_batches=selection_exclude_open_batches,
            loop_id_for_filter=loop_id_for_filter,
        )
        rows = list((await session.exec(sample_stmt)).all())
        page, next_cursor = self._paginate_rows(rows, limit=limit, offset=offset)

        items: list[pb.DataItem] = []
        for sample, asset in page:
            item = self._build_sample_data_item(sample=sample, asset=asset)
            if item is None:
                continue
            items.append(item)
        return items, next_cursor

    async def _list_commit_annotation_mappings(
        self,
        *,
        session,
        commit_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[CommitAnnotationMap], str | None]:
        mapping_stmt = (
            select(CommitAnnotationMap)
            .where(CommitAnnotationMap.commit_id == commit_id)
            .order_by(CommitAnnotationMap.sample_id)
            .offset(offset)
            .limit(limit + 1)
        )
        mappings_all = list((await session.exec(mapping_stmt)).all())
        mappings_page_raw, next_cursor = self._paginate_rows(mappings_all, limit=limit, offset=offset)
        return list(mappings_page_raw), next_cursor

    async def _load_annotations_map(
        self,
        *,
        session,
        mappings: list[CommitAnnotationMap],
    ) -> dict[uuid.UUID, Annotation]:
        annotation_ids = [item.annotation_id for item in mappings]
        if not annotation_ids:
            return {}
        ann_stmt = select(Annotation).where(Annotation.id.in_(annotation_ids))
        ann_rows = list((await session.exec(ann_stmt)).all())
        return {item.id: item for item in ann_rows}

    async def _load_sample_size_map(
        self,
        *,
        session,
        mappings: list[CommitAnnotationMap],
    ) -> dict[uuid.UUID, tuple[int, int]]:
        sample_ids = list({item.sample_id for item in mappings})
        if not sample_ids:
            return {}

        sample_stmt = (
            select(Sample, Asset)
            .join(Asset, Sample.primary_asset_id == Asset.id, isouter=True)
            .where(Sample.id.in_(sample_ids))
        )
        sample_size_map: dict[uuid.UUID, tuple[int, int]] = {}
        for sample, asset in (await session.exec(sample_stmt)).all():
            width = 0
            height = 0
            if asset:
                meta = asset.meta_info or {}
                width = int(meta.get("width") or 0)
                height = int(meta.get("height") or 0)
            sample_size_map[sample.id] = (width, height)
        return sample_size_map

    @staticmethod
    def _build_annotation_geometry(
        *,
        ann: Annotation,
        sample_size_map: dict[uuid.UUID, tuple[int, int]],
    ) -> tuple[list[float], dict | None]:
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
            return bbox_xywh, obb

        if ann.type == AnnotationType.OBB:
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
        return bbox_xywh, obb

    def _build_annotation_data_item(
        self,
        *,
        ann: Annotation,
        sample_size_map: dict[uuid.UUID, tuple[int, int]],
    ) -> pb.DataItem:
        bbox_xywh, obb = self._build_annotation_geometry(
            ann=ann,
            sample_size_map=sample_size_map,
        )
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
        return pb.DataItem(annotation_item=item)

    async def _query_annotations_items(
        self,
        *,
        session,
        commit_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[pb.DataItem], str | None]:
        mappings, next_cursor = await self._list_commit_annotation_mappings(
            session=session,
            commit_id=commit_id,
            limit=limit,
            offset=offset,
        )
        ann_map = await self._load_annotations_map(session=session, mappings=mappings)
        sample_size_map = await self._load_sample_size_map(session=session, mappings=mappings)

        items: list[pb.DataItem] = []
        for mapping in mappings:
            ann = ann_map.get(mapping.annotation_id)
            if not ann:
                continue
            items.append(
                self._build_annotation_data_item(
                    ann=ann,
                    sample_size_map=sample_size_map,
                )
            )

        return items, next_cursor

    @staticmethod
    def _build_plugin_capabilities(register: pb.Register) -> list[dict[str, object]]:
        plugin_capabilities: list[dict[str, object]] = []
        for item in register.plugins:
            plugin_id = str(item.plugin_id or "").strip()
            if not plugin_id:
                continue
            supported_accelerators = [
                runtime_codec.accelerator_type_to_text(v)
                for v in item.supported_accelerators
                if runtime_codec.accelerator_type_to_text(v)
            ]
            supports_auto_fallback = bool(item.supports_auto_fallback)
            if not supported_accelerators and not supports_auto_fallback:
                # Proto3 bool cannot distinguish "unset" from false; keep backward-compatible default.
                supports_auto_fallback = True
            plugin_capabilities.append(
                {
                    "plugin_id": plugin_id,
                    "display_name": str(item.display_name or plugin_id),
                    "version": str(item.version or ""),
                    "supported_job_types": [str(v) for v in item.supported_job_types],
                    "supported_strategies": [str(v) for v in item.supported_strategies],
                    "request_config_schema": runtime_codec.struct_to_dict(item.request_config_schema),
                    "default_request_config": runtime_codec.struct_to_dict(item.default_request_config),
                    "supported_accelerators": supported_accelerators,
                    "supports_auto_fallback": supports_auto_fallback,
                }
            )
        return plugin_capabilities

    @staticmethod
    def _apply_reject_close_policy(state: _RuntimeStreamState) -> bool:
        if settings.RUNTIME_STREAM_REJECT_CLOSE:
            state.close_stream_after_flush = True
            return False
        return True

    async def _emit_register_reject(
        self,
        *,
        state: _RuntimeStreamState,
        register: pb.Register,
        code: str,
        message: str,
        reason: str,
    ) -> bool:
        request_id = str(register.request_id or "")
        await self._emit_stream_error(
            state=state,
            code=code,
            message=message,
            request_id=request_id or None,
            reply_to=request_id,
            reason=reason,
        )
        return self._apply_reject_close_policy(state)

    def _build_dispatcher_register_kwargs(
        self,
        *,
        state: _RuntimeStreamState,
        register: pb.Register,
        executor_id: str,
        plugin_capabilities: list[dict[str, object]],
    ) -> dict[str, object]:
        plugin_ids = {item["plugin_id"] for item in plugin_capabilities}
        resources = runtime_codec.resource_summary_to_dict(register.resources)
        register_kwargs: dict[str, object] = {
            "executor_id": executor_id,
            "queue": state.outbox,
            "version": str(register.version or ""),
            "plugin_ids": plugin_ids,
            "resources": resources,
        }
        if "plugin_capabilities" in inspect.signature(runtime_dispatcher.register).parameters:
            register_kwargs["plugin_capabilities"] = plugin_capabilities
        return register_kwargs

    async def _emit_stream_error(
        self,
        *,
        state: _RuntimeStreamState,
        code: str,
        message: str,
        request_id: str | None,
        reply_to: str,
        reason: str,
        job_id: str | None = None,
        query_type: int | None = None,
    ) -> None:
        await state.outbox.put(
            runtime_codec.build_error_message(
                code=code,
                message=message,
                request_id=request_id,
                reply_to=reply_to,
                reason=reason,
                job_id=job_id,
                query_type=query_type,
            )
        )

    async def _handle_stream_register(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        register = message.register
        state.executor_id = str(register.executor_id or "")
        executor_id = state.executor_id

        logger.info(
            "收到执行器注册请求 executor_id={} version={} plugin_count={}",
            executor_id or "<empty>",
            str(register.version or ""),
            len(register.plugins),
        )
        if not executor_id:
            return await self._emit_register_reject(
                state=state,
                register=register,
                code="INVALID_ARGUMENT",
                message="executor_id is required",
                reason="executor_id is required",
            )

        plugin_capabilities = self._build_plugin_capabilities(register)
        try:
            register_kwargs = self._build_dispatcher_register_kwargs(
                state=state,
                register=register,
                executor_id=executor_id,
                plugin_capabilities=plugin_capabilities,
            )
            await runtime_dispatcher.register(**register_kwargs)
        except PermissionError as exc:
            logger.warning("执行器注册被拒绝 executor_id={} reason={}", executor_id, exc)
            return await self._emit_register_reject(
                state=state,
                register=register,
                code="FORBIDDEN",
                message=str(exc),
                reason=str(exc),
            )
        except Exception as exc:
            logger.exception("执行器注册失败 executor_id={} error={}", executor_id, exc)
            error_text = f"register failed: {exc}"
            return await self._emit_register_reject(
                state=state,
                register=register,
                code="INTERNAL",
                message=error_text,
                reason=error_text,
            )

        await state.outbox.put(
            runtime_codec.build_ack_message(
                ack_for=register.request_id,
                status=pb.OK,
                ack_type="register",
                ack_reason="registered",
                detail="registered",
            )
        )
        logger.info("执行器注册成功 executor_id={}", executor_id)
        return True

    async def _handle_stream_heartbeat(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        heartbeat = message.heartbeat
        if not state.executor_id:
            return True
        await runtime_dispatcher.heartbeat(
            executor_id=state.executor_id,
            busy=bool(heartbeat.busy),
            current_job_id=heartbeat.current_job_id or None,
            resources=runtime_codec.resource_summary_to_dict(heartbeat.resources),
        )
        return True

    async def _handle_stream_job_event(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        request = message.job_event
        request_id = str(request.request_id or "")
        duplicated, _ = state.dedup_cache.get(request_id, "job_event")
        if duplicated:
            logger.info("忽略重复 job_event request_id={}", request_id)
            return True

        await self._persist_job_event(request)
        if request_id:
            state.dedup_cache.remember(request_id, "job_event")
        return True

    async def _handle_stream_job_result(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        request = message.job_result
        request_id = str(request.request_id or "")
        duplicated, _ = state.dedup_cache.get(request_id, "job_result")
        if duplicated:
            logger.info("忽略重复 job_result request_id={}", request_id)
            return True

        await self._persist_job_result(request)
        logger.info(
            "收到任务结果并完成持久化 request_id={} job_id={} status={}",
            request_id,
            request.job_id,
            request.status,
        )
        if state.executor_id:
            await runtime_dispatcher.mark_executor_idle(
                executor_id=state.executor_id,
                job_id=request.job_id,
            )
        if request_id:
            state.dedup_cache.remember(request_id, "job_result")
        return True

    async def _handle_stream_data_request(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        request = message.data_request
        request_id = str(request.request_id or "")
        duplicated, cached_response = state.dedup_cache.get(request_id, "data_request")
        if duplicated:
            if cached_response is not None:
                await state.outbox.put(cached_response)
            logger.info("命中 data_request 幂等缓存 request_id={}", request_id)
            return True

        try:
            response = await self._build_data_response(request)
        except ValueError as exc:
            response = runtime_codec.build_error_message(
                code="INVALID_ARGUMENT",
                message=str(exc),
                request_id=request.request_id or None,
                reply_to=request.request_id,
                job_id=request.job_id,
                query_type=int(request.query_type),
                reason=str(exc),
            )
        except Exception as exc:
            logger.exception(
                "data_request 处理失败 request_id={} job_id={} query_type={} error={}",
                request.request_id,
                request.job_id,
                runtime_codec.query_type_to_text(request.query_type),
                exc,
            )
            response = runtime_codec.build_error_message(
                code="INTERNAL",
                message=f"data request failed: {exc}",
                request_id=request.request_id or None,
                reply_to=request.request_id,
                job_id=request.job_id,
                query_type=int(request.query_type),
                reason=f"data request failed: {exc}",
            )
        await state.outbox.put(response)
        if request_id:
            state.dedup_cache.remember(request_id, "data_request", response=response)
        return True

    async def _handle_stream_upload_ticket_request(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        request = message.upload_ticket_request
        request_id = str(request.request_id or "")
        duplicated, cached_response = state.dedup_cache.get(request_id, "upload_ticket_request")
        if duplicated:
            if cached_response is not None:
                await state.outbox.put(cached_response)
            logger.info("命中 upload_ticket_request 幂等缓存 request_id={}", request_id)
            return True

        try:
            response = await self._build_upload_ticket_response(request)
        except ValueError as exc:
            response = runtime_codec.build_error_message(
                code="INVALID_ARGUMENT",
                message=str(exc),
                request_id=request.request_id or None,
                reply_to=request.request_id,
                job_id=request.job_id,
                reason=str(exc),
            )
        except Exception as exc:
            response = runtime_codec.build_error_message(
                code="INTERNAL",
                message=f"upload ticket failed: {exc}",
                request_id=request.request_id or None,
                reply_to=request.request_id,
                job_id=request.job_id,
                reason=f"upload ticket failed: {exc}",
            )
        await state.outbox.put(response)
        if request_id:
            state.dedup_cache.remember(request_id, "upload_ticket_request", response=response)
        return True

    async def _handle_stream_ack(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        ack = message.ack
        request_id = str(ack.request_id or "")
        duplicated, _ = state.dedup_cache.get(request_id, "ack")
        if duplicated:
            logger.info("忽略重复 ack request_id={} ack_for={}", request_id, ack.ack_for)
            return True
        await runtime_dispatcher.handle_ack(
            ack_for=str(ack.ack_for or ""),
            status=int(ack.status),
            ack_type=int(ack.type),
            ack_reason=int(ack.reason),
            detail=ack.detail or None,
        )
        if request_id:
            state.dedup_cache.remember(request_id, "ack")
        return True

    async def _handle_stream_error(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        del state
        err = message.error
        logger.error(
            "收到执行器错误消息 code={} message={} reason={} reply_to={} ack_for={}",
            err.code,
            err.message,
            err.reason,
            err.reply_to,
            err.ack_for,
        )
        return True

    async def _dispatch_stream_message(
        self,
        *,
        message: pb.RuntimeMessage,
        state: _RuntimeStreamState,
    ) -> bool:
        payload_type = message.WhichOneof("payload")
        if payload_type == "register":
            return await self._handle_stream_register(message=message, state=state)
        if payload_type == "heartbeat":
            return await self._handle_stream_heartbeat(message=message, state=state)
        if payload_type == "job_event":
            return await self._handle_stream_job_event(message=message, state=state)
        if payload_type == "job_result":
            return await self._handle_stream_job_result(message=message, state=state)
        if payload_type == "data_request":
            return await self._handle_stream_data_request(message=message, state=state)
        if payload_type == "upload_ticket_request":
            return await self._handle_stream_upload_ticket_request(message=message, state=state)
        if payload_type == "ack":
            return await self._handle_stream_ack(message=message, state=state)
        if payload_type == "error":
            return await self._handle_stream_error(message=message, state=state)
        logger.warning("未知 runtime 消息类型 payload_type={}", payload_type)
        return True

    async def Stream(self, request_iterator, context):
        metadata = dict(context.invocation_metadata())
        if metadata.get("x-internal-token") != settings.INTERNAL_TOKEN:
            logger.warning("拒绝未授权 runtime 连接 peer={}", context.peer())
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid internal token")

        state = _RuntimeStreamState(
            outbox=asyncio.Queue(),
            dedup_cache=_RequestDedupCache(
                ttl_sec=settings.RUNTIME_REQUEST_IDEMPOTENCY_TTL_SEC,
                max_entries=settings.RUNTIME_REQUEST_IDEMPOTENCY_MAX_ENTRIES,
            ),
        )

        async def _reader() -> None:
            async for message in request_iterator:
                try:
                    should_continue = await self._dispatch_stream_message(message=message, state=state)
                    if not should_continue:
                        break
                except Exception:
                    logger.exception("处理 runtime 消息失败")

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                if reader_task.done() and state.outbox.empty():
                    break
                try:
                    payload = await asyncio.wait_for(state.outbox.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if state.close_stream_after_flush and state.outbox.empty():
                        break
                    continue
                yield payload
                if state.close_stream_after_flush and state.outbox.empty():
                    break
        finally:
            reader_task.cancel()
            if state.executor_id:
                logger.info("runtime 流已关闭，开始注销执行器 executor_id={}", state.executor_id)
                await runtime_dispatcher.unregister(state.executor_id)

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
                self._apply_status_event(
                    job=job,
                    status_enum=status_enum,
                    payload=payload,
                    event_ts=event_ts,
                )
            elif event_type == "metric":
                await self._apply_metric_event(
                    session=session,
                    job=job,
                    job_id=job_id,
                    payload=payload,
                    event_ts=event_ts,
                )
            elif event_type == "artifact":
                self._apply_artifact_event(job=job, payload=payload)

            session.add(job)
            await session.commit()

    @staticmethod
    def _apply_status_event(
            *,
            job: Job,
            status_enum: int,
            payload: dict[str, object],
            event_ts: datetime,
    ) -> None:
        mapped = _map_status(status_enum)
        job.status = mapped
        if mapped == TrainingJobStatus.RUNNING and not job.started_at:
            job.started_at = event_ts
        if mapped in (
            TrainingJobStatus.SUCCESS,
            TrainingJobStatus.FAILED,
            TrainingJobStatus.PARTIAL_FAILED,
            TrainingJobStatus.CANCELLED,
        ):
            job.ended_at = event_ts
        if mapped in (TrainingJobStatus.FAILED, TrainingJobStatus.PARTIAL_FAILED):
            job.last_error = payload.get("reason") or payload.get("message")

    @staticmethod
    def _parse_metric_payload(payload: dict[str, object]) -> tuple[int, int | None, dict[str, float]]:
        step = int(payload.get("step") or 0)
        raw_epoch = payload.get("epoch")
        epoch: int | None
        try:
            epoch = int(raw_epoch) if raw_epoch is not None else None
        except Exception:
            epoch = None

        raw_metrics = payload.get("metrics")
        if not isinstance(raw_metrics, dict):
            return step, epoch, {}

        metrics: dict[str, float] = {}
        for metric_name, metric_value in raw_metrics.items():
            try:
                metrics[str(metric_name)] = float(metric_value)
            except Exception:
                continue
        return step, epoch, metrics

    async def _apply_metric_event(
            self,
            *,
            session,
            job: Job,
            job_id: uuid.UUID,
            payload: dict[str, object],
            event_ts: datetime,
    ) -> None:
        step, epoch, metrics = self._parse_metric_payload(payload)
        if not metrics:
            return

        metric_names = list(metrics.keys())
        existing_stmt = (
            select(JobMetricPoint)
            .where(
                JobMetricPoint.job_id == job_id,
                JobMetricPoint.step == step,
                JobMetricPoint.metric_name.in_(metric_names),
            )
        )
        existing_points = list((await session.exec(existing_stmt)).all())
        existing_map = {point.metric_name: point for point in existing_points}

        aggregated = dict(job.metrics or {})
        for metric_name, value in metrics.items():
            aggregated[metric_name] = value
            existing = existing_map.get(metric_name)
            if existing:
                existing.metric_value = value
                existing.epoch = epoch
                existing.ts = event_ts
                session.add(existing)
                continue
            session.add(
                JobMetricPoint(
                    job_id=job_id,
                    step=step,
                    epoch=epoch,
                    metric_name=metric_name,
                    metric_value=value,
                    ts=event_ts,
                )
            )
        job.metrics = aggregated

    @staticmethod
    def _apply_artifact_event(*, job: Job, payload: dict[str, object]) -> None:
        name = str(payload.get("name") or "")
        uri = str(payload.get("uri") or "")
        if not name or not _is_downloadable_artifact_uri(uri):
            return
        artifacts = dict(job.artifacts or {})
        artifacts[name] = {
            "kind": payload.get("kind", "artifact"),
            "uri": uri,
            "meta": payload.get("meta") or {},
        }
        job.artifacts = artifacts

    @staticmethod
    def _parse_result_metrics(message: pb.JobResult) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for key, value in message.metrics.items():
            try:
                metrics[str(key)] = float(value)
            except Exception:
                continue
        return metrics

    @staticmethod
    def _parse_result_artifacts(message: pb.JobResult) -> dict[str, dict[str, object]]:
        artifacts: dict[str, dict[str, object]] = {}
        for item in message.artifacts:
            name = str(item.name or "")
            if not name:
                continue
            uri = str(item.uri or "")
            if not _is_downloadable_artifact_uri(uri):
                continue
            artifacts[name] = {
                "kind": str(item.kind or "artifact"),
                "uri": uri,
                "meta": runtime_codec.struct_to_dict(item.meta),
            }
        return artifacts

    @staticmethod
    def _split_candidate_reason(reason: object) -> tuple[dict[str, object], dict[str, object]]:
        if not isinstance(reason, dict):
            return {}, {}
        extra = dict(reason)
        prediction_snapshot: dict[str, object] = {}
        snapshot = extra.get("prediction_snapshot")
        if isinstance(snapshot, dict):
            prediction_snapshot = snapshot
            extra = {key: value for key, value in extra.items() if key != "prediction_snapshot"}
        return extra, prediction_snapshot

    def _parse_result_candidates(self, message: pb.JobResult) -> dict[uuid.UUID, dict[str, object]]:
        candidates: dict[uuid.UUID, dict[str, object]] = {}
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
            extra, prediction_snapshot = self._split_candidate_reason(reason)
            # 同一个 sample_id 在同一消息出现多次时，保留最后一个（通常是最新分数）。
            candidates[sample_id] = {
                "score": score,
                "extra": extra,
                "prediction_snapshot": prediction_snapshot,
            }
        return candidates

    async def _upsert_job_sample_metrics(
            self,
            *,
            session,
            job_id: uuid.UUID,
            candidate_rows: dict[uuid.UUID, dict[str, object]],
    ) -> None:
        if not candidate_rows:
            return

        sample_ids = list(candidate_rows.keys())
        existing_stmt = select(JobSampleMetric).where(
            JobSampleMetric.job_id == job_id,
            JobSampleMetric.sample_id.in_(sample_ids),
        )
        existing_rows = list((await session.exec(existing_stmt)).all())
        existing_map = {item.sample_id: item for item in existing_rows}

        for sample_id, payload in candidate_rows.items():
            score = float(payload.get("score") or 0.0)
            extra = dict(payload.get("extra") or {})
            prediction_snapshot = dict(payload.get("prediction_snapshot") or {})

            existing = existing_map.get(sample_id)
            if existing:
                existing.score = score
                existing.extra = extra
                existing.prediction_snapshot = prediction_snapshot
                session.add(existing)
                continue

            session.add(
                JobSampleMetric(
                    job_id=job_id,
                    sample_id=sample_id,
                    score=score,
                    extra=extra,
                    prediction_snapshot=prediction_snapshot,
                )
            )

    async def _persist_job_result(self, message: pb.JobResult) -> None:
        job_id_raw = message.job_id
        if not job_id_raw:
            return
        try:
            job_id = uuid.UUID(str(job_id_raw))
        except Exception:
            return

        metrics = self._parse_result_metrics(message)
        artifacts = self._parse_result_artifacts(message)
        candidate_rows = self._parse_result_candidates(message)

        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return

            mapped = _map_status(int(message.status))
            job.status = mapped
            job.metrics = {**(job.metrics or {}), **metrics}
            job.artifacts = {**(job.artifacts or {}), **artifacts}
            job.ended_at = datetime.now(UTC)
            if mapped in (TrainingJobStatus.FAILED, TrainingJobStatus.PARTIAL_FAILED):
                job.last_error = str(message.error_message or "runtime failed")

            await self._upsert_job_sample_metrics(
                session=session,
                job_id=job_id,
                candidate_rows=candidate_rows,
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

        async with SessionLocal() as session:
            if query_type == "labels":
                project_id = _parse_uuid(message.project_id, "project_id")
                items, next_cursor = await self._query_labels_items(
                    session=session,
                    project_id=project_id,
                    limit=limit,
                    offset=offset,
                )
            elif query_type in {"samples", "unlabeled_samples"}:
                project_id = _parse_uuid(message.project_id, "project_id")
                commit_id = _parse_uuid(message.commit_id, "commit_id") if query_type == "unlabeled_samples" else None
                items, next_cursor = await self._query_samples_items(
                    session=session,
                    query_type=query_type,
                    project_id=project_id,
                    commit_id=commit_id,
                    job_id_raw=str(message.job_id or ""),
                    limit=limit,
                    offset=offset,
                )
            elif query_type == "annotations":
                commit_id = _parse_uuid(message.commit_id, "commit_id")
                items, next_cursor = await self._query_annotations_items(
                    session=session,
                    commit_id=commit_id,
                    limit=limit,
                    offset=offset,
                )

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
                logger.exception("运行时 watchdog 轮询失败")

    async def start(self) -> None:
        recovery = await runtime_dispatcher.recover_after_api_restart()
        logger.info("运行时 dispatcher 恢复摘要 summary={}", recovery)
        self._server.add_insecure_port(settings.RUNTIME_GRPC_BIND)
        await self._server.start()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("运行时 gRPC 服务已启动 bind={}", settings.RUNTIME_GRPC_BIND)

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
