from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.core.config import settings
from saki_api.models.enums import ALLoopStatus, AuthorType, LoopRoundStatus, TaskType, TrainingJobStatus
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.project import Project
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.loop_round import LoopRound
from saki_api.models.l3.model import Model
from saki_api.services.loop_orchestrator import LoopOrchestrator


@pytest.fixture
async def orchestrator_env(tmp_path):
    db_path = tmp_path / "loop_orchestrator.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    orchestrator = LoopOrchestrator(interval_sec=2)
    try:
        yield session_local, orchestrator
    finally:
        await engine.dispose()


async def _seed_loop_graph(session_local: async_sessionmaker[AsyncSession]) -> tuple[Project, Branch, ALLoop]:
    async with session_local() as session:
        project = Project(
            name="loop-project",
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
        await session.flush()
        await session.refresh(branch)

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            query_strategy="aug_iou_disagreement_v1",
            model_arch="yolo_det_v1",
            global_config={},
            current_iteration=0,
            is_active=True,
            status=ALLoopStatus.RUNNING,
            max_rounds=5,
            query_batch_size=10,
            min_seed_labeled=1,
            min_new_labels_per_round=2,
            stop_patience_rounds=2,
            stop_min_gain=0.001,
            auto_register_model=False,
        )
        session.add(loop)
        await session.commit()
        await session.refresh(branch)
        await session.refresh(loop)
        await session.refresh(project)
        return project, branch, loop


@pytest.mark.anyio
async def test_create_round_job_inherits_resources_and_warm_start(orchestrator_env):
    session_local, orchestrator = orchestrator_env
    project, branch, loop = await _seed_loop_graph(session_local)

    class _DummyStorage:
        @staticmethod
        def get_presigned_url(object_name: str):
            return f"https://example.test/download/{object_name}"

    orchestrator._storage = _DummyStorage()  # noqa: SLF001

    async with session_local() as session:
        db_loop = await session.get(ALLoop, loop.id)
        assert db_loop is not None
        db_loop.global_config = {
            "job_resources_default": {
                "gpu_count": 1,
                "capabilities": ["obb", "cuda"],
                "labels": {"zone": "cn-north"},
            },
            "warm_start": True,
            "selection": {"exclude_open_batches": True, "min_candidates_required": 1},
        }

        parent_model = Model(
            project_id=project.id,
            job_id=None,
            source_commit_id=branch.head_commit_id,
            parent_model_id=None,
            plugin_id="yolo_det_v1",
            model_arch="yolo_det_v1",
            name="parent-model",
            version_tag="r0",
            weights_path=f"s3://{settings.MINIO_BUCKET_NAME}/runtime/jobs/prev/best.pt",
            status="candidate",
            metrics={},
            artifacts={},
        )
        session.add(parent_model)
        await session.flush()
        await session.refresh(parent_model)

        db_loop.latest_model_id = parent_model.id
        session.add(db_loop)
        await session.flush()

        job_id = await orchestrator._create_round_job(  # noqa: SLF001
            session=session,
            loop=db_loop,
            source_commit_id=branch.head_commit_id,
        )
        await session.commit()

        job = await session.get(Job, job_id)
        assert job is not None
        assert job.resources["gpu_count"] == 1
        assert job.resources["labels"]["zone"] == "cn-north"
        assert job.params["warm_start"] is True
        assert job.params["parent_model_id"] == str(parent_model.id)
        assert job.params["base_model"] == f"s3://{settings.MINIO_BUCKET_NAME}/runtime/jobs/prev/best.pt"
        assert "base_model_download_url" in job.params
        assert "split_seed" in job.params


@pytest.mark.anyio
async def test_training_round_without_candidates_completes_loop(orchestrator_env):
    session_local, orchestrator = orchestrator_env
    project, branch, loop = await _seed_loop_graph(session_local)

    async with session_local() as session:
        job = Job(
            project_id=project.id,
            loop_id=loop.id,
            iteration=1,
            round_index=1,
            status=TrainingJobStatus.SUCCESS,
            source_commit_id=branch.head_commit_id,
            job_type="train_detection",
            plugin_id="yolo_det_v1",
            mode="active_learning",
            query_strategy="aug_iou_disagreement_v1",
            params={},
            resources={},
            strategy_params={},
            metrics={"map50": 0.41},
            artifacts={},
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)

        round_obj = LoopRound(
            loop_id=loop.id,
            round_index=1,
            source_commit_id=branch.head_commit_id,
            job_id=job.id,
            status=LoopRoundStatus.TRAINING,
            metrics={},
            selected_count=0,
            labeled_count=0,
        )
        session.add(round_obj)
        await session.commit()

    async with session_local() as session:
        db_loop = await session.get(ALLoop, loop.id)
        db_round = await session.exec(select(LoopRound).where(LoopRound.loop_id == loop.id))
        db_round_obj = db_round.first()
        db_branch = await session.get(Branch, branch.id)
        assert db_loop is not None
        assert db_round_obj is not None
        assert db_branch is not None

        dispatch_job_id = await orchestrator._handle_training_round(  # noqa: SLF001
            session=session,
            loop=db_loop,
            round_obj=db_round_obj,
            branch=db_branch,
        )
        assert dispatch_job_id is None
        await session.commit()

        await session.refresh(db_loop)
        await session.refresh(db_round_obj)
        assert db_round_obj.status == LoopRoundStatus.COMPLETED_NO_CANDIDATES
        assert db_round_obj.selected_count == 0
        assert db_loop.status == ALLoopStatus.COMPLETED
        assert db_loop.is_active is False
        assert db_loop.last_error == "no_candidates"

        batch_rows = await session.exec(select(AnnotationBatch).where(AnnotationBatch.job_id == job.id))
        assert batch_rows.first() is None


@pytest.mark.anyio
async def test_refresh_batch_progress_backfills_annotation_commit(orchestrator_env):
    session_local, orchestrator = orchestrator_env
    project, branch, loop = await _seed_loop_graph(session_local)

    sample_id = uuid.uuid4()
    annotation_id = uuid.uuid4()

    async with session_local() as session:
        job = Job(
            project_id=project.id,
            loop_id=loop.id,
            iteration=1,
            round_index=1,
            status=TrainingJobStatus.SUCCESS,
            source_commit_id=branch.head_commit_id,
            job_type="train_detection",
            plugin_id="yolo_det_v1",
            mode="active_learning",
            query_strategy="aug_iou_disagreement_v1",
            params={},
            resources={},
            strategy_params={},
            metrics={},
            artifacts={},
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)

        batch = AnnotationBatch(
            project_id=project.id,
            loop_id=loop.id,
            job_id=job.id,
            round_index=1,
            total_count=1,
            annotated_count=0,
            meta={},
        )
        session.add(batch)
        await session.flush()
        await session.refresh(batch)

        batch_item = AnnotationBatchItem(
            batch_id=batch.id,
            sample_id=sample_id,
            rank=1,
            score=0.9,
            reason={},
            prediction_snapshot={},
            is_annotated=False,
            annotation_commit_id=None,
        )
        session.add(batch_item)

        from saki_api.models.l2.camap import CommitAnnotationMap
        session.add(
            CommitAnnotationMap(
                commit_id=branch.head_commit_id,
                sample_id=sample_id,
                annotation_id=annotation_id,
                project_id=project.id,
            )
        )
        await session.commit()

    async with session_local() as session:
        db_batch = await session.exec(select(AnnotationBatch).where(AnnotationBatch.loop_id == loop.id))
        batch = db_batch.first()
        assert batch is not None

        await orchestrator._refresh_batch_progress(  # noqa: SLF001
            session=session,
            batch=batch,
            commit_id=branch.head_commit_id,
        )
        await session.commit()

        item_row = await session.exec(select(AnnotationBatchItem).where(AnnotationBatchItem.batch_id == batch.id))
        item = item_row.first()
        assert item is not None
        assert item.is_annotated is True
        assert item.annotation_commit_id == branch.head_commit_id
