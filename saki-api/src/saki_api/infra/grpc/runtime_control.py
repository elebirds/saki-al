"""Runtime-domain gRPC server used by dispatcher."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import grpc
from loguru import logger
from sqlmodel import select

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
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
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.runtime.service.runtime_service import RuntimeService
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.shared.modeling.enums import AuthorType, CommitSampleReviewState, StepType


def _parse_uuid(raw: str) -> uuid.UUID | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except Exception:
        return None


def _resolve_task_id(task_id: str) -> str:
    return str(task_id or "").strip()


def _build_activation_key(loop_id: uuid.UUID, round_index: int, sample_ids: list[uuid.UUID]) -> str:
    unique_sorted_ids = sorted({str(sample_id) for sample_id in sample_ids if sample_id})
    digest = hashlib.sha256(",".join(unique_sorted_ids).encode("utf-8")).hexdigest()
    return f"{loop_id}:{int(round_index)}:{digest}"


def _to_domain_data_response(response: pb.DataResponse) -> domain_pb.DataResponse:
    task_id = _resolve_task_id(response.task_id)
    return domain_pb.DataResponse(
        request_id=str(response.request_id or ""),
        reply_to=str(response.reply_to or ""),
        task_id=task_id,
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

    async def _resolve_step_by_task_id(self, *, session, task_id: uuid.UUID) -> Step | None:
        rows = list(
            (
                await session.exec(
                    select(Step)
                    .where((Step.task_id == task_id) | (Step.id == task_id))
                    .limit(2)
                )
            ).all()
        )
        if not rows:
            return None
        for row in rows:
            if row.task_id == task_id:
                return row
        return rows[0]

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

    async def ResolveRoundReveal(self, request, context):  # noqa: N802
        loop_id = _parse_uuid(request.loop_id)
        branch_id = _parse_uuid(request.branch_id)
        round_id = _parse_uuid(request.round_id)
        min_required = max(1, int(request.min_required or 1))
        force = bool(request.force)
        if loop_id is None or round_id is None:
            return domain_pb.ResolveRoundRevealResponse(
                revealed_count=0,
                selected_count=0,
                missing_count=0,
                latest_commit_id="",
                revealable_sample_ids_hash="",
                effective_min_required=0,
                pool_hidden_before=0,
                pool_hidden_after=0,
                train_visible_after=0,
                total_train_universe=0,
            )

        async with SessionLocal() as session:
            runtime_service = RuntimeService(session)
            try:
                result = await runtime_service.resolve_round_reveal(
                    loop_id=loop_id,
                    round_id=round_id,
                    branch_id=branch_id,
                    force=force,
                    min_required=min_required,
                )
                await session.commit()
            except (BadRequestAppException, NotFoundAppException) as exc:
                await session.rollback()
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(str(exc))
                return domain_pb.ResolveRoundRevealResponse(
                    revealed_count=0,
                    selected_count=0,
                    missing_count=0,
                    latest_commit_id="",
                    revealable_sample_ids_hash="",
                    effective_min_required=0,
                    pool_hidden_before=0,
                    pool_hidden_after=0,
                    train_visible_after=0,
                    total_train_universe=0,
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("resolve round reveal failed loop_id={} round_id={} error={}", loop_id, round_id, exc)
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("resolve round reveal failed")
                return domain_pb.ResolveRoundRevealResponse(
                    revealed_count=0,
                    selected_count=0,
                    missing_count=0,
                    latest_commit_id="",
                    revealable_sample_ids_hash="",
                    effective_min_required=0,
                    pool_hidden_before=0,
                    pool_hidden_after=0,
                    train_visible_after=0,
                    total_train_universe=0,
                )

            latest_commit_id = result.get("latest_commit_id")
            return domain_pb.ResolveRoundRevealResponse(
                revealed_count=int(result.get("revealed_count", 0)),
                selected_count=int(result.get("selected_count", 0)),
                missing_count=int(result.get("missing_count", 0)),
                latest_commit_id=str(latest_commit_id or ""),
                revealable_sample_ids_hash=str(result.get("revealable_sample_ids_hash") or ""),
                effective_min_required=int(result.get("effective_min_required", 0)),
                pool_hidden_before=int(result.get("pool_hidden_before", 0)),
                pool_hidden_after=int(result.get("pool_hidden_after", 0)),
                train_visible_after=int(result.get("train_visible_after", 0)),
                total_train_universe=int(result.get("total_train_universe", 0)),
            )

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

    async def ActivateSamples(self, request, context):  # noqa: N802
        project_id = _parse_uuid(request.project_id)
        branch_id = _parse_uuid(request.branch_id)
        oracle_commit_id = _parse_uuid(request.oracle_commit_id)
        source_commit_id = _parse_uuid(request.source_commit_id)

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
        task_id = _resolve_task_id(request.task_id)
        response_messages = await self._runtime_ingress.handle_data_request(
            pb.DataRequest(
                request_id=str(request.request_id or ""),
                task_id=task_id,
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
        task_id = _resolve_task_id(request.task_id)
        response_message = await self._runtime_ingress.handle_upload_ticket_request(
            pb.UploadTicketRequest(
                request_id=str(request.request_id or ""),
                task_id=task_id,
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
                task_id=task_id,
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
                task_id=task_id,
                upload_url="",
                storage_uri="",
                headers={},
            )
        upload_ticket = response_message.upload_ticket_response
        upload_task_id = _resolve_task_id(upload_ticket.task_id)
        return domain_pb.UploadTicketResponse(
            request_id=str(upload_ticket.request_id or ""),
            reply_to=str(upload_ticket.reply_to or ""),
            task_id=upload_task_id,
            upload_url=str(upload_ticket.upload_url or ""),
            storage_uri=str(upload_ticket.storage_uri or ""),
            headers=dict(upload_ticket.headers),
        )

    async def CreateDownloadTicket(self, request, context):  # noqa: N802
        request_id = str(request.request_id or "") or str(uuid.uuid4())
        task_id = _parse_uuid(request.task_id)
        artifact_name = str(request.artifact_name or "").strip()
        if task_id is None or not artifact_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("task_id/artifact_name are required")
            return domain_pb.DownloadTicketResponse(
                request_id=request_id,
                reply_to=request_id,
                task_id=str(request.task_id or ""),
                artifact_name=artifact_name,
                download_url="",
                storage_uri="",
                headers={},
            )

        async with SessionLocal() as session:
            step = await self._resolve_step_by_task_id(session=session, task_id=task_id)
            if step is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("task not found")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri="",
                    headers={},
                )

            artifact_map = step.artifacts if isinstance(step.artifacts, dict) else {}
            artifact = artifact_map.get(artifact_name)
            if not isinstance(artifact, dict):
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("artifact not found")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri="",
                    headers={},
                )

            uri = str(artifact.get("uri") or "").strip()
            if not uri:
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details("artifact uri is empty")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri="",
                    headers={},
                )

            if uri.startswith("http://") or uri.startswith("https://"):
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url=uri,
                    storage_uri=uri,
                    headers={},
                )

            if not uri.startswith("s3://"):
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details("unsupported artifact uri")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri=uri,
                    headers={},
                )

            _, _, bucket_and_path = uri.partition("s3://")
            _, _, object_path = bucket_and_path.partition("/")
            object_path = object_path.strip()
            if not object_path:
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details("invalid s3 uri")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri=uri,
                    headers={},
                )

            try:
                download_url = self.storage.get_presigned_url(
                    object_name=object_path,
                    expires_delta=timedelta(hours=settings.RUNTIME_DOWNLOAD_URL_EXPIRE_HOURS),
                )
            except Exception as exc:
                logger.exception(
                    "failed to issue download ticket task_id={} artifact={} error={}",
                    task_id,
                    artifact_name,
                    exc,
                )
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("failed to issue download ticket")
                return domain_pb.DownloadTicketResponse(
                    request_id=request_id,
                    reply_to=request_id,
                    task_id=str(task_id),
                    artifact_name=artifact_name,
                    download_url="",
                    storage_uri=uri,
                    headers={},
                )

            return domain_pb.DownloadTicketResponse(
                request_id=request_id,
                reply_to=request_id,
                task_id=str(task_id),
                artifact_name=artifact_name,
                download_url=download_url,
                storage_uri=uri,
                headers={},
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
