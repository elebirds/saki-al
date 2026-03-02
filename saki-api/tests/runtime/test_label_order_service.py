from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.project.api.label import LabelCreate
from saki_api.modules.project.domain.project import Project
from saki_api.modules.project.service.label import LabelService
from saki_api.modules.shared.modeling.enums import TaskType


@pytest.fixture
async def label_order_env(tmp_path):
    db_path = tmp_path / "label_order_service.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_project(session: AsyncSession, *, name: str) -> Project:
    project = Project(name=name, task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()
    return project


@pytest.mark.anyio
async def test_create_label_appends_contiguous_sort_order(label_order_env):
    session_local = label_order_env
    async with session_local() as session:
        project = await _seed_project(session, name="project-label-order")
        service = LabelService(session)

        await service.create_label(LabelCreate(project_id=project.id, name="car", color="#f00"))
        await service.create_label(LabelCreate(project_id=project.id, name="bus", color="#0f0"))
        await service.create_label(LabelCreate(project_id=project.id, name="truck", color="#00f"))

        labels = await service.get_by_project(project.id)
        assert [item.name for item in labels] == ["car", "bus", "truck"]
        assert [item.sort_order for item in labels] == [1, 2, 3]


@pytest.mark.anyio
async def test_reorder_requires_complete_permutation_and_persists_order(label_order_env):
    session_local = label_order_env
    async with session_local() as session:
        project = await _seed_project(session, name="project-label-reorder")
        service = LabelService(session)

        a = await service.create_label(LabelCreate(project_id=project.id, name="a", color="#111"))
        b = await service.create_label(LabelCreate(project_id=project.id, name="b", color="#222"))
        c = await service.create_label(LabelCreate(project_id=project.id, name="c", color="#333"))

        with pytest.raises(BadRequestAppException):
            await service.reorder(project.id, [a.id, b.id])
        with pytest.raises(BadRequestAppException):
            await service.reorder(project.id, [a.id, b.id, b.id])
        with pytest.raises(BadRequestAppException):
            await service.reorder(project.id, [a.id, b.id, uuid.uuid4()])

        reordered = await service.reorder(project.id, [c.id, a.id, b.id])
        assert [item.id for item in reordered] == [c.id, a.id, b.id]
        assert [item.sort_order for item in reordered] == [1, 2, 3]


@pytest.mark.anyio
async def test_delete_label_compacts_sort_order(label_order_env):
    session_local = label_order_env
    async with session_local() as session:
        project = await _seed_project(session, name="project-label-delete")
        service = LabelService(session)

        first = await service.create_label(LabelCreate(project_id=project.id, name="first", color="#111"))
        second = await service.create_label(LabelCreate(project_id=project.id, name="second", color="#222"))
        third = await service.create_label(LabelCreate(project_id=project.id, name="third", color="#333"))

        await service.delete_label(label_id=second.id, project_id=project.id)

        labels = await service.get_by_project(project.id)
        assert [item.id for item in labels] == [first.id, third.id]
        assert [item.sort_order for item in labels] == [1, 2]
