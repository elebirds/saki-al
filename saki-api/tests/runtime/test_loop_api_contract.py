from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.api.api_v1.endpoints.l3 import query as loop_query_endpoint
from saki_api.db.session import _session_ctx
from saki_api.models.enums import AuthorType, TaskType
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.project import Project
from saki_api.schemas.l3.job import LoopCreateRequest, LoopRead, LoopUpdateRequest
from saki_api.services.job import JobService


@pytest.fixture
async def loop_api_env(tmp_path):
    db_path = tmp_path / "loop_api_contract.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_project_branch(session: AsyncSession) -> tuple[Project, Branch]:
    project = Project(
        name="loop-contract-project",
        task_type=TaskType.DETECTION,
        config={},
    )
    session.add(project)
    await session.flush()
    await session.refresh(project)

    init_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
    )
    session.add(init_commit)
    await session.flush()
    await session.refresh(init_commit)

    branch = Branch(
        project_id=project.id,
        name="master",
        head_commit_id=init_commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.commit()
    await session.refresh(project)
    await session.refresh(branch)
    return project, branch


@pytest.mark.anyio
async def test_loop_read_model_validate_accepts_orm_instance(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-a",
                    branch_id=branch.id,
                    model_request_config={"epochs": 12, "batch": 8},
                ),
            )
        finally:
            _session_ctx.reset(token)

        parsed = LoopRead.model_validate(loop)
        assert parsed.id == loop.id
        assert parsed.project_id == project.id


@pytest.mark.anyio
async def test_loop_endpoints_create_list_get_update_contract(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_project_loop(
                project_id=project.id,
                payload=LoopCreateRequest(
                    name="loop-b",
                    branch_id=branch.id,
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                    global_config={"warm_start": False},
                    model_request_config={"epochs": 24, "batch": 16},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.model_request_config == {"epochs": 24, "batch": 16}
            assert created.global_config["warm_start"] is False

            listed = await loop_query_endpoint.list_project_loops(
                project_id=project.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(listed) == 1
            assert listed[0].id == created.id
            assert listed[0].model_request_config["epochs"] == 24

            fetched = await loop_query_endpoint.get_loop(
                loop_id=created.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert fetched.id == created.id
            assert fetched.model_request_config["batch"] == 16

            updated = await loop_query_endpoint.update_loop(
                loop_id=created.id,
                payload=LoopUpdateRequest(
                    model_arch="demo_det_v1",
                    query_strategy="random_baseline",
                    model_request_config={"epochs": 30, "lr": 0.001},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert updated.model_arch == "demo_det_v1"
            assert updated.query_strategy == "random_baseline"
            assert updated.model_request_config == {"epochs": 30, "lr": 0.001}
        finally:
            _session_ctx.reset(token)
