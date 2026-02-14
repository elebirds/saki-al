"""Runtime-domain gRPC server used by dispatcher."""

from __future__ import annotations

import uuid

import grpc
from loguru import logger

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
from saki_api.modules.runtime.service.ingress.control_ingress_service import RuntimeControlIngressService
from saki_api.modules.shared.modeling.enums import AuthorType


def _parse_uuid(raw: str) -> uuid.UUID | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except Exception:
        return None


def _to_domain_data_item(item: pb.DataItem) -> domain_pb.DataItem:
    target = domain_pb.DataItem()
    item_type = item.WhichOneof("item")
    if item_type == "label_item":
        target.label_item.id = str(item.label_item.id or "")
        target.label_item.name = str(item.label_item.name or "")
        target.label_item.color = str(item.label_item.color or "")
        return target
    if item_type == "sample_item":
        target.sample_item.id = str(item.sample_item.id or "")
        target.sample_item.asset_hash = str(item.sample_item.asset_hash or "")
        target.sample_item.download_url = str(item.sample_item.download_url or "")
        target.sample_item.width = int(item.sample_item.width or 0)
        target.sample_item.height = int(item.sample_item.height or 0)
        target.sample_item.meta.CopyFrom(item.sample_item.meta)
        return target
    if item_type == "annotation_item":
        target.annotation_item.id = str(item.annotation_item.id or "")
        target.annotation_item.sample_id = str(item.annotation_item.sample_id or "")
        target.annotation_item.category_id = str(item.annotation_item.category_id or "")
        target.annotation_item.bbox_xywh.extend([float(v) for v in item.annotation_item.bbox_xywh])
        target.annotation_item.obb.CopyFrom(item.annotation_item.obb)
        target.annotation_item.source = str(item.annotation_item.source or "")
        target.annotation_item.confidence = float(item.annotation_item.confidence or 0.0)
        return target
    return target


def _to_domain_data_response(response: pb.DataResponse) -> domain_pb.DataResponse:
    return domain_pb.DataResponse(
        request_id=str(response.request_id or ""),
        reply_to=str(response.reply_to or ""),
        task_id=str(response.task_id or ""),
        query_type=int(response.query_type),
        items=[_to_domain_data_item(item) for item in response.items],
        next_cursor=str(response.next_cursor or ""),
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

    async def CreateSimulationCommitFromOracle(self, request, context):  # noqa: N802
        project_id = _parse_uuid(request.project_id)
        branch_id = _parse_uuid(request.branch_id)
        oracle_commit_id = _parse_uuid(request.oracle_commit_id)
        source_commit_id = _parse_uuid(request.source_commit_id)

        if project_id is None or branch_id is None or oracle_commit_id is None:
            return domain_pb.CreateSimulationCommitFromOracleResponse(created=False, commit_id="")

        async with SessionLocal() as session:
            branch_repo = BranchRepository(session)
            branch = await branch_repo.get_by_id(branch_id)
            if not branch or branch.project_id != project_id:
                return domain_pb.CreateSimulationCommitFromOracleResponse(created=False, commit_id="")

            parent_commit_id = source_commit_id or branch.head_commit_id
            if parent_commit_id is None:
                return domain_pb.CreateSimulationCommitFromOracleResponse(created=False, commit_id="")

            commit = Commit(
                project_id=project_id,
                parent_id=parent_commit_id,
                message=(
                    f"[sim] loop={request.loop_id or '-'} round={int(request.round_index)} "
                    f"strategy={request.query_strategy or '-'} topk={int(request.topk)}"
                ),
                author_type=AuthorType.SYSTEM,
                author_id=None,
                stats={},
                extra={
                    "runtime": {
                        "command_id": str(request.command_id or ""),
                        "loop_id": str(request.loop_id or ""),
                        "round_index": int(request.round_index),
                        "query_strategy": str(request.query_strategy or ""),
                        "topk": int(request.topk),
                        "oracle_commit_id": str(oracle_commit_id),
                        "source_commit_id": str(parent_commit_id),
                    }
                },
                commit_hash="",
            )
            session.add(commit)
            await session.flush()

            camap_repo = CAMapRepository(session)
            source_state = await camap_repo.get_annotations_for_commit(oracle_commit_id)
            mappings: list[tuple[uuid.UUID, uuid.UUID]] = []
            for sample_id, annotation_ids in source_state.items():
                for annotation_id in annotation_ids:
                    mappings.append((sample_id, annotation_id))
            if mappings:
                await camap_repo.set_commit_state(
                    commit_id=commit.id,
                    mappings=mappings,
                    project_id=project_id,
                )

            sample_state_repo = CommitSampleStateRepository(session)
            await sample_state_repo.copy_commit_state(
                source_commit_id=parent_commit_id,
                target_commit_id=commit.id,
                project_id=project_id,
            )

            commit.stats = await camap_repo.get_commit_stats(commit.id)
            await refresh_commit_hash(session, commit)
            session.add(commit)
            await session.commit()

            return domain_pb.CreateSimulationCommitFromOracleResponse(
                created=True,
                commit_id=str(commit.id),
            )

    async def ActivateSamples(self, request, context):  # noqa: N802
        legacy_response = await self.CreateSimulationCommitFromOracle(
            domain_pb.CreateSimulationCommitFromOracleRequest(
                command_id=str(request.command_id or ""),
                project_id=str(request.project_id or ""),
                branch_id=str(request.branch_id or ""),
                oracle_commit_id=str(request.oracle_commit_id or ""),
                source_commit_id=str(request.source_commit_id or ""),
                loop_id=str(request.loop_id or ""),
                round_index=int(request.round_index or 0),
                query_strategy=str(request.query_strategy or ""),
                topk=int(request.topk or 0),
            ),
            context,
        )
        return domain_pb.ActivateSamplesResponse(
            created=bool(legacy_response.created),
            commit_id=str(legacy_response.commit_id or ""),
        )

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
        response_message = await self._runtime_ingress.handle_data_request(
            pb.DataRequest(
                request_id=str(request.request_id or ""),
                task_id=str(request.task_id or ""),
                query_type=int(request.query_type),
                project_id=str(request.project_id or ""),
                commit_id=str(request.commit_id or ""),
                cursor=str(request.cursor or ""),
                limit=int(request.limit or 0),
            )
        )
        payload_type = response_message.WhichOneof("payload")
        if payload_type == "error":
            error_payload = response_message.error
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(error_payload.reason or error_payload.message or "query data failed"))
            return domain_pb.DataResponse(
                request_id=str(request.request_id or ""),
                reply_to=str(request.request_id or ""),
                task_id=str(request.task_id or ""),
                query_type=int(request.query_type),
                items=[],
                next_cursor="",
            )
        if payload_type != "data_response":
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("runtime ingress returned unexpected payload")
            return domain_pb.DataResponse(
                request_id=str(request.request_id or ""),
                reply_to=str(request.request_id or ""),
                task_id=str(request.task_id or ""),
                query_type=int(request.query_type),
                items=[],
                next_cursor="",
            )
        return _to_domain_data_response(response_message.data_response)

    async def CreateUploadTicket(self, request, context):  # noqa: N802
        response_message = await self._runtime_ingress.handle_upload_ticket_request(
            pb.UploadTicketRequest(
                request_id=str(request.request_id or ""),
                task_id=str(request.task_id or ""),
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
                task_id=str(request.task_id or ""),
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
                task_id=str(request.task_id or ""),
                upload_url="",
                storage_uri="",
                headers={},
            )
        upload_ticket = response_message.upload_ticket_response
        return domain_pb.UploadTicketResponse(
            request_id=str(upload_ticket.request_id or ""),
            reply_to=str(upload_ticket.reply_to or ""),
            task_id=str(upload_ticket.task_id or ""),
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
