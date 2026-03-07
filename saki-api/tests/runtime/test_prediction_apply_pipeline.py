from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.modules.access.domain.access import User
from saki_api.modules.annotation.domain.annotation import Annotation
from saki_api.modules.annotation.domain.camap import CommitAnnotationMap
from saki_api.modules.annotation.domain.draft import AnnotationDraft
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.model import Model
from saki_api.modules.runtime.domain.model_class_schema import ModelClassSchema
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.runtime.service.runtime_service import RuntimeService
from saki_api.modules.shared.modeling.enums import (
    AnnotationSource,
    AnnotationType,
    AuthorType,
    CommitSampleReviewState,
    RuntimeTaskStatus,
    TaskType,
)
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample
from saki_api.core.exceptions import BadRequestAppException


@dataclass
class _PredictionSeedContext:
    actor: User
    project: Project
    branch: Branch
    init_commit: Commit
    loop: Loop
    round_row: Round
    sample: Sample
    model: Model
    labels_sorted_by_sort: list[Label]


@pytest.fixture
async def prediction_env(tmp_path):
    db_path = tmp_path / "prediction_pipeline.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_prediction_context(session: AsyncSession) -> _PredictionSeedContext:
    actor = User(email=f"actor-{uuid.uuid4()}@example.com", hashed_password="hashed")
    session.add(actor)
    await session.flush()

    dataset = Dataset(name=f"dataset-{uuid.uuid4()}", owner_id=actor.id)
    session.add(dataset)
    await session.flush()

    sample = Sample(dataset_id=dataset.id, name="sample-a", asset_group={})
    session.add(sample)
    await session.flush()

    project = Project(name=f"project-{uuid.uuid4()}", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

    init_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
        commit_hash=f"init-{uuid.uuid4()}",
    )
    session.add(init_commit)
    await session.flush()

    branch = Branch(
        project_id=project.id,
        name="master",
        head_commit_id=init_commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.flush()

    label_a = Label(project_id=project.id, name="car", color="#ff0000", sort_order=2)
    label_b = Label(project_id=project.id, name="bus", color="#00ff00", sort_order=1)
    session.add(label_a)
    session.add(label_b)
    await session.flush()

    loop = Loop(
        project_id=project.id,
        branch_id=branch.id,
        name="loop-prediction-set",
        model_arch="demo_det_v1",
    )
    session.add(loop)
    await session.flush()

    round_row = Round(
        project_id=project.id,
        loop_id=loop.id,
        round_index=1,
        plugin_id="demo_det_v1",
        input_commit_id=init_commit.id,
        final_artifacts={"best.pt": {"kind": "weights", "uri": "https://example.com/models/best.pt"}},
    )
    session.add(round_row)
    await session.flush()

    labels_sorted = list(
        (
            await session.exec(
                select(Label).where(Label.project_id == project.id).order_by(Label.sort_order.asc(), Label.id.asc())
            )
        ).all()
    )
    model = Model(
        project_id=project.id,
        source_commit_id=init_commit.id,
        source_round_id=round_row.id,
        plugin_id="demo_det_v1",
        model_arch="demo_det_v1",
        name="demo-r1",
        version_tag="r1-a1",
        primary_artifact_name="best.pt",
        weights_path="https://example.com/models/best.pt",
        status="candidate",
        artifacts={"best.pt": {"kind": "weights", "uri": "https://example.com/models/best.pt"}},
        publish_manifest={},
        created_by=actor.id,
    )
    session.add(model)
    await session.flush()

    session.add_all(
        [
            ModelClassSchema(
                model_id=model.id,
                label_id=labels_sorted[0].id,
                class_index=0,
                class_name=labels_sorted[0].name,
                class_name_norm=labels_sorted[0].name.lower(),
                schema_hash="schema-demo-r1",
            ),
            ModelClassSchema(
                model_id=model.id,
                label_id=labels_sorted[1].id,
                class_index=1,
                class_name=labels_sorted[1].name,
                class_name_norm=labels_sorted[1].name.lower(),
                schema_hash="schema-demo-r1",
            ),
        ]
    )
    await session.flush()
    await session.commit()

    return _PredictionSeedContext(
        actor=actor,
        project=project,
        branch=branch,
        init_commit=init_commit,
        loop=loop,
        round_row=round_row,
        sample=sample,
        model=model,
        labels_sorted_by_sort=labels_sorted,
    )


async def _seed_committed_annotation(
    *,
    session: AsyncSession,
    commit_id: uuid.UUID,
    project_id: uuid.UUID,
    sample_id: uuid.UUID,
    label_id: uuid.UUID,
    annotator_id: uuid.UUID,
) -> Annotation:
    annotation_id = uuid.uuid4()
    annotation = Annotation(
        id=annotation_id,
        project_id=project_id,
        sample_id=sample_id,
        label_id=label_id,
        group_id=annotation_id,
        lineage_id=annotation_id,
        view_role="main",
        parent_id=None,
        type=AnnotationType.RECT,
        source=AnnotationSource.MANUAL,
        geometry={"rect": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0}},
        attrs={"seed": "manual"},
        confidence=1.0,
        annotator_id=annotator_id,
    )
    session.add(annotation)
    await session.flush()

    session.add(
        CommitAnnotationMap(
            commit_id=commit_id,
            sample_id=sample_id,
            annotation_id=annotation.id,
            project_id=project_id,
        )
    )
    await session.flush()
    return annotation


async def _create_prediction_task(
    *,
    service: RuntimeService,
    ctx: _PredictionSeedContext,
    scope_status: str = "all",
    predict_conf: float | None = None,
    params: dict | None = None,
):
    payload = {
        "model_id": str(ctx.model.id),
        "artifact_name": "best.pt",
        "target_branch_id": str(ctx.branch.id),
        "base_commit_id": str(ctx.init_commit.id),
        "scope_type": "sample_status",
        "scope_payload": {"status": scope_status},
        "params": dict(params or {}),
    }
    if predict_conf is not None:
        payload["predict_conf"] = float(predict_conf)
    return await service.create_prediction(
        project_id=ctx.project.id,
        payload=payload,
        actor_user_id=ctx.actor.id,
    )


async def _finish_prediction_task(
    *,
    session: AsyncSession,
    task_id: uuid.UUID,
    rows: list[dict],
) -> None:
    task_row = await session.get(Task, task_id)
    assert task_row is not None
    existing_candidates = await session.exec(
        select(TaskCandidateItem).where(TaskCandidateItem.task_id == task_id)
    )
    for item in list(existing_candidates.all()):
        await session.delete(item)

    for idx, row in enumerate(rows, start=1):
        reason_payload = dict(row.get("reason") or {})
        snapshot_payload = row.get("prediction_snapshot")
        if not isinstance(snapshot_payload, dict):
            raw_snapshot = reason_payload.get("prediction_snapshot")
            snapshot_payload = raw_snapshot if isinstance(raw_snapshot, dict) else {}
        session.add(
            TaskCandidateItem(
                task_id=task_id,
                sample_id=uuid.UUID(str(row["sample_id"])),
                rank=idx,
                score=float(row.get("score", 0.0)),
                reason=reason_payload,
                prediction_snapshot=dict(snapshot_payload),
            )
        )
    task_row.status = RuntimeTaskStatus.SUCCEEDED
    session.add(task_row)
    await session.commit()


@pytest.mark.anyio
async def test_generate_prediction_creates_queued_prediction_task_without_step(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")

        assert prediction.status == "queued"
        assert prediction.project_id == ctx.project.id
        assert prediction.plugin_id == "demo_det_v1"
        assert prediction.task_id is not None
        task_row = await session.get(Task, prediction.task_id)
        assert task_row is not None
        assert task_row.status == RuntimeTaskStatus.READY


@pytest.mark.anyio
async def test_generate_prediction_not_require_loop_round_context(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        model_row = await session.get(Model, ctx.model.id)
        assert model_row is not None
        model_row.source_round_id = None
        session.add(model_row)
        await session.flush()

        round_row = await session.get(Round, ctx.round_row.id)
        assert round_row is not None
        await session.delete(round_row)
        loop_row = await session.get(Loop, ctx.loop.id)
        assert loop_row is not None
        await session.delete(loop_row)
        await session.commit()

        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")
        assert prediction.task_id is not None
        task_row = await session.get(Task, prediction.task_id)
        assert task_row is not None
        task_meta = (
            task_row.resolved_params.get("_prediction_task")
            if isinstance(task_row.resolved_params, dict)
            else {}
        )
        assert isinstance(task_meta, dict)
        assert task_meta.get("target_branch_id") == str(ctx.branch.id)
        assert "target_round_id" not in task_meta
        assert "loop_id" not in task_meta


@pytest.mark.anyio
async def test_generate_prediction_supports_model_id_payload(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        prediction = await service.create_prediction(
            project_id=ctx.project.id,
            payload={
                "model_id": str(ctx.model.id),
                "artifact_name": "best.pt",
                "target_branch_id": str(ctx.branch.id),
                "base_commit_id": str(ctx.init_commit.id),
                "scope_type": "sample_status",
                "scope_payload": {"status": "all"},
            },
            actor_user_id=ctx.actor.id,
        )

        assert prediction.id is not None
        assert prediction.model_id == ctx.model.id
        assert prediction.task_id is not None


@pytest.mark.anyio
async def test_generate_prediction_persists_predict_conf_to_plugin_params(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        prediction = await _create_prediction_task(
            service=service,
            ctx=ctx,
            scope_status="all",
            predict_conf=0.02,
        )
        task_row = await session.get(Task, prediction.task_id)
        assert task_row is not None
        predict_params = (
            task_row.resolved_params.get("predict")
            if isinstance(task_row.resolved_params, dict)
            else {}
        )
        assert isinstance(predict_params, dict)
        assert float(predict_params.get("predict_conf")) == pytest.approx(0.02)


@pytest.mark.anyio
async def test_generate_prediction_rejects_invalid_predict_conf(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)
        with pytest.raises(BadRequestAppException, match="predict_conf must be in range \\[0, 1\\]"):
            await _create_prediction_task(
                service=service,
                ctx=ctx,
                scope_status="all",
                predict_conf=1.5,
            )


@pytest.mark.anyio
async def test_generate_prediction_rejects_sampling_topk_for_predict(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)
        with pytest.raises(BadRequestAppException, match="predict does not support sampling parameters"):
            await _create_prediction_task(
                service=service,
                ctx=ctx,
                scope_status="all",
                params={
                    "sampling": {
                        "strategy": "uncertainty_1_minus_max_conf",
                        "topk": 100,
                    }
                },
            )


@pytest.mark.anyio
async def test_generate_prediction_requires_model_class_schema(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        rows = await session.exec(select(ModelClassSchema).where(ModelClassSchema.model_id == ctx.model.id))
        for row in list(rows.all()):
            await session.delete(row)
        await session.commit()

        service = RuntimeService(session)
        with pytest.raises(BadRequestAppException, match="PREDICTION_SCHEMA_MISSING"):
            await _create_prediction_task(service=service, ctx=ctx, scope_status="all")


@pytest.mark.anyio
async def test_materialize_prediction_from_reason_snapshot_with_cls_mapping(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")
        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.77,
                    "reason": {
                        "strategy": "uncertainty",
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[0].name,
                                    "confidence": 0.91,
                                    "geometry": {
                                        "rect": {
                                            "x": 10,
                                            "y": 20,
                                            "width": 100,
                                            "height": 100,
                                        }
                                    },
                                }
                            ]
                        },
                    },
                    "prediction_snapshot": {},
                }
            ],
        )

        settled = await service.get_prediction_task(task_id=prediction.task_id)
        assert settled.status == "ready"

        _, items = await service.get_prediction_detail(
            prediction_id=prediction.id,
            item_limit=10,
        )
        assert len(items) == 1
        item = items[0]
        assert item.sample_id == ctx.sample.id
        assert item.label_id == ctx.labels_sorted_by_sort[0].id
        assert item.confidence == pytest.approx(0.91)
        rect = (item.geometry or {}).get("rect") or {}
        assert rect.get("x") == pytest.approx(10.0)
        assert rect.get("y") == pytest.approx(20.0)
        assert rect.get("width") == pytest.approx(100.0)
        assert rect.get("height") == pytest.approx(100.0)


@pytest.mark.anyio
async def test_settle_prediction_skips_empty_prediction_snapshot_rows(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        sample_b = Sample(dataset_id=ctx.sample.dataset_id, name="sample-empty-skip", asset_group={})
        session.add(sample_b)
        await session.commit()

        service = RuntimeService(session)
        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")
        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.12,
                    "reason": {"strategy": "predict"},
                    "prediction_snapshot": {"base_predictions": []},
                },
                {
                    "sample_id": sample_b.id,
                    "score": 0.88,
                    "reason": {"strategy": "predict"},
                    "prediction_snapshot": {
                        "base_predictions": [
                            {
                                "class_index": 0,
                                "class_name": ctx.labels_sorted_by_sort[0].name,
                                "confidence": 0.88,
                                "geometry": {
                                    "rect": {
                                        "x": 4,
                                        "y": 5,
                                        "width": 20,
                                        "height": 30,
                                    }
                                },
                            }
                        ]
                    },
                },
            ],
        )

        settled = await service.get_prediction_task(task_id=prediction.task_id)
        assert str(settled.status or "").lower() == "ready"
        _, items = await service.get_prediction_detail(prediction_id=prediction.id, item_limit=10)
        assert len(items) == 1
        assert items[0].sample_id == sample_b.id


@pytest.mark.anyio
async def test_sample_status_unlabeled_filters_labeled_samples(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        sample_b = Sample(dataset_id=ctx.sample.dataset_id, name="sample-b", asset_group={})
        session.add(sample_b)
        await session.flush()

        session.add(
            CommitSampleState(
                commit_id=ctx.init_commit.id,
                sample_id=ctx.sample.id,
                project_id=ctx.project.id,
                state=CommitSampleReviewState.LABELED,
            )
        )
        await session.commit()

        service = RuntimeService(session)
        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="unlabeled")

        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.66,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[0].name,
                                    "confidence": 0.66,
                                    "geometry": {
                                        "rect": {
                                            "x": 1,
                                            "y": 2,
                                            "width": 10,
                                            "height": 10,
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                },
                {
                    "sample_id": sample_b.id,
                    "score": 0.55,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[0].name,
                                    "confidence": 0.55,
                                    "geometry": {
                                        "rect": {
                                            "x": 2,
                                            "y": 3,
                                            "width": 10,
                                            "height": 10,
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                },
            ],
        )

        _, items = await service.get_prediction_detail(prediction_id=prediction.id, item_limit=10)
        assert len(items) == 1
        assert items[0].sample_id == sample_b.id


@pytest.mark.anyio
async def test_apply_prediction_merges_head_commit_and_expands_multi_predictions(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        committed_ann = await _seed_committed_annotation(
            session=session,
            commit_id=ctx.init_commit.id,
            project_id=ctx.project.id,
            sample_id=ctx.sample.id,
            label_id=ctx.labels_sorted_by_sort[0].id,
            annotator_id=ctx.actor.id,
        )
        await session.commit()

        service = RuntimeService(session)
        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")

        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.8,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 1,
                                    "class_name": ctx.labels_sorted_by_sort[1].name,
                                    "confidence": 0.88,
                                    "geometry": {
                                        "rect": {
                                            "x": 5,
                                            "y": 6,
                                            "width": 10,
                                            "height": 20,
                                        }
                                    },
                                },
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[0].name,
                                    "confidence": 0.77,
                                    "geometry": {
                                        "rect": {
                                            "x": 30,
                                            "y": 40,
                                            "width": 40,
                                            "height": 50,
                                        }
                                    },
                                },
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                }
            ],
        )

        result = await service.apply_prediction(
            prediction_id=prediction.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )
        assert result["applied_count"] == 2

        draft = await session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == ctx.project.id,
                AnnotationDraft.sample_id == ctx.sample.id,
                AnnotationDraft.user_id == ctx.actor.id,
                AnnotationDraft.branch_name == "master",
            )
        )
        row = draft.one_or_none()
        assert row is not None
        payload = row.payload if isinstance(row.payload, dict) else {}
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        assert len(annotations) == 3

        manual_rows = [row for row in annotations if str(row.get("source") or "").lower() == "manual"]
        model_rows = [row for row in annotations if str(row.get("source") or "").lower() == "model"]
        assert len(manual_rows) == 1
        assert len(model_rows) == 2

        manual = manual_rows[0]
        assert manual.get("id") == str(committed_ann.id)
        assert manual.get("label_id") == str(committed_ann.label_id)

        for ann in model_rows:
            assert ann.get("type") == "rect"
            assert isinstance(ann.get("group_id"), str) and ann.get("group_id")
            assert isinstance(ann.get("lineage_id"), str) and ann.get("lineage_id")


@pytest.mark.anyio
async def test_apply_prediction_can_be_reapplied_without_model_duplication(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        committed_ann = await _seed_committed_annotation(
            session=session,
            commit_id=ctx.init_commit.id,
            project_id=ctx.project.id,
            sample_id=ctx.sample.id,
            label_id=ctx.labels_sorted_by_sort[0].id,
            annotator_id=ctx.actor.id,
        )
        await session.commit()

        service = RuntimeService(session)
        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")
        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.83,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 1,
                                    "class_name": ctx.labels_sorted_by_sort[1].name,
                                    "confidence": 0.9,
                                    "geometry": {
                                        "rect": {"x": 5, "y": 6, "width": 10, "height": 20}
                                    },
                                },
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[0].name,
                                    "confidence": 0.8,
                                    "geometry": {
                                        "rect": {"x": 30, "y": 40, "width": 40, "height": 50}
                                    },
                                },
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                }
            ],
        )

        first = await service.apply_prediction(
            prediction_id=prediction.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )
        second = await service.apply_prediction(
            prediction_id=prediction.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )

        assert first["applied_count"] == 2
        assert second["applied_count"] == 2
        assert str(second.get("status") or "").lower() == "applied"

        draft = await session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == ctx.project.id,
                AnnotationDraft.sample_id == ctx.sample.id,
                AnnotationDraft.user_id == ctx.actor.id,
                AnnotationDraft.branch_name == "master",
            )
        )
        row = draft.one_or_none()
        assert row is not None
        payload = row.payload if isinstance(row.payload, dict) else {}
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
        assert len(annotations) == 3

        manual_rows = [item for item in annotations if str(item.get("source") or "").lower() == "manual"]
        model_rows = [item for item in annotations if str(item.get("source") or "").lower() == "model"]
        assert len(manual_rows) == 1
        assert len(model_rows) == 2
        assert manual_rows[0].get("id") == str(committed_ann.id)


@pytest.mark.anyio
async def test_apply_prediction_fails_on_unresolvable_label(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)

        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")

        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.5,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "confidence": 0.5,
                                    "geometry": {
                                        "rect": {
                                            "x": 1,
                                            "y": 2,
                                            "width": 2,
                                            "height": 2,
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                }
            ],
        )

        result = await service.apply_prediction(
            prediction_id=prediction.id,
            actor_user_id=ctx.actor.id,
            branch_name="master",
            dry_run=False,
        )
        assert result["applied_count"] == 0
        assert str(result.get("status") or "").lower() == "failed"

        draft_row = await session.exec(
            select(AnnotationDraft).where(
                AnnotationDraft.project_id == ctx.project.id,
                AnnotationDraft.sample_id == ctx.sample.id,
                AnnotationDraft.user_id == ctx.actor.id,
                AnnotationDraft.branch_name == "master",
            )
        )
        assert draft_row.one_or_none() is None
        settled = await service.get_prediction_task(task_id=prediction.task_id)
        assert str(settled.status or "").lower() == "failed"
        assert "IR_PREDICTION_FIELD_MISSING" in str(settled.last_error or "")


@pytest.mark.anyio
async def test_generate_prediction_requires_base_commit_id(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)
        with pytest.raises(BadRequestAppException):
            await service.create_prediction(
                project_id=ctx.project.id,
                payload={
                    "model_id": str(ctx.model.id),
                    "artifact_name": "best.pt",
                    "target_branch_id": str(ctx.branch.id),
                    "scope_type": "sample_status",
                    "scope_payload": {"status": "all"},
                },
                actor_user_id=ctx.actor.id,
            )


@pytest.mark.anyio
async def test_generate_prediction_rejects_legacy_payload_fields(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)
        with pytest.raises(BadRequestAppException, match="legacy prediction fields are not supported"):
            await service.create_prediction(
                project_id=ctx.project.id,
                payload={
                    "model_id": str(ctx.model.id),
                    "artifact_name": "best.pt",
                    "target_branch_id": str(ctx.branch.id),
                    "base_commit_id": str(ctx.init_commit.id),
                    "scope_type": "sample_status",
                    "scope_payload": {"status": "all"},
                    "model_source": {"kind": "model", "model_id": str(ctx.model.id)},
                },
                actor_user_id=ctx.actor.id,
            )


@pytest.mark.anyio
async def test_settle_prediction_fails_on_class_name_and_index_conflict(prediction_env):
    session_local = prediction_env
    async with session_local() as session:
        ctx = await _seed_prediction_context(session)
        service = RuntimeService(session)
        prediction = await _create_prediction_task(service=service, ctx=ctx, scope_status="all")

        await _finish_prediction_task(
            session=session,
            task_id=prediction.task_id,
            rows=[
                {
                    "sample_id": ctx.sample.id,
                    "score": 0.66,
                    "reason": {
                        "prediction_snapshot": {
                            "base_predictions": [
                                {
                                    "class_index": 0,
                                    "class_name": ctx.labels_sorted_by_sort[1].name,
                                    "confidence": 0.66,
                                    "geometry": {
                                        "rect": {
                                            "x": 8,
                                            "y": 9,
                                            "width": 10,
                                            "height": 10,
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "prediction_snapshot": {},
                }
            ],
        )

        settled = await service.get_prediction_task(task_id=prediction.task_id)
        assert str(settled.status or "").lower() == "failed"
        assert "PREDICTION_LABEL_CONFLICT" in str(settled.last_error or "")
