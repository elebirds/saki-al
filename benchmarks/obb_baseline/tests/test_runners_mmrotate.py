from __future__ import annotations

import inspect
import json
import os
from collections import abc as collections_abc
import collections
from pathlib import Path
import sys
from types import ModuleType

import pytest


def test_apply_python_compat_shims_restores_collections_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_python_compat_shims

    original_value = getattr(collections, "Sequence", None)
    if hasattr(collections, "Sequence"):
        monkeypatch.delattr(collections, "Sequence")

    _apply_python_compat_shims()

    assert collections.Sequence is collections_abc.Sequence

    if original_value is not None:
        monkeypatch.setattr(collections, "Sequence", original_value)


def test_build_mmrotate_command_uses_generated_config_contract(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import build_mmrotate_train_command

    signature = inspect.signature(build_mmrotate_train_command)
    assert tuple(signature.parameters) == (
        "model_name",
        "run_dir",
        "generated_config",
        "work_dir",
        "train_seed",
        "device",
    )

    generated_config = tmp_path / "configs" / "oriented_rcnn.py"
    command = build_mmrotate_train_command(
        model_name="oriented_rcnn_r50",
        run_dir=tmp_path / "runs" / "oriented_rcnn_r50",
        generated_config=generated_config,
        work_dir=tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101",
        train_seed=101,
        device="cuda:0",
    )

    assert command[:7] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
        "python",
        "-m",
        "obb_baseline.runners_mmrotate",
    ]
    assert "--config" in command
    assert str(generated_config) in command
    assert "--work-dir" in command
    assert str(tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101") in command
    assert "--seed" in command
    assert "101" in command
    assert "--device" in command
    assert "cuda:0" in command


@pytest.mark.parametrize(
    ("model_name", "expected_preset", "expected_base_marker"),
    [
        (
            "oriented_rcnn_r50",
            "oriented_rcnn",
            "oriented_rcnn/oriented-rcnn-le90_r50_fpn_1x_dota.py",
        ),
        (
            "roi_transformer_r50",
            "roi_transformer",
            "roi_trans/roi-trans-le90_r50_fpn_1x_dota.py",
        ),
        ("r3det_r50", "r3det", "r3det/r3det-oc_r50_fpn_1x_dota.py"),
        (
            "rtmdet_rotated_m",
            "rtmdet_rotated",
            "rotated_rtmdet/rotated_rtmdet_m-3x-dota.py",
        ),
    ],
)
def test_render_mmrotate_config_supports_all_presets(
    tmp_path: Path,
    model_name: str,
    expected_preset: str,
    expected_base_marker: str,
) -> None:
    from obb_baseline.runners_mmrotate import render_mmrotate_config

    signature = inspect.signature(render_mmrotate_config)
    assert "classes" in signature.parameters
    assert "class_names" not in signature.parameters

    config_text = render_mmrotate_config(
        model_name=model_name,
        data_root=tmp_path / "dataset",
        work_dir=tmp_path / "workdirs" / model_name / "split-11" / "seed-101",
        train_seed=101,
        score_thr=0.25,
        classes=("plane", "ship"),
        mmrotate_batch_size=4,
        mmrotate_workers=8,
        mmrotate_amp=True,
    )

    assert f'preset = "{expected_preset}"' in config_text
    assert expected_base_marker in config_text
    assert f'data_root = r"{(tmp_path / "dataset").as_posix()}/"' in config_text
    assert (
        f'work_dir = r"{(tmp_path / "workdirs" / model_name / "split-11" / "seed-101").as_posix()}"'
        in config_text
    )
    assert "train_seed = 101" in config_text
    assert "score_thr = 0.25" in config_text
    assert "mmrotate_batch_size = 4" in config_text
    assert "mmrotate_workers = 8" in config_text
    assert "mmrotate_amp = True" in config_text
    assert "classes = ('plane', 'ship')" in config_text
    assert "class_names = ('plane', 'ship')" in config_text
    assert "num_classes = 2" in config_text


def test_render_mmrotate_config_overrides_materialized_dota_split_layout(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import render_mmrotate_config

    data_root = tmp_path / "views" / "dota" / "split-11"
    config_text = render_mmrotate_config(
        model_name="oriented_rcnn_r50",
        data_root=data_root,
        work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
        train_seed=101,
        score_thr=0.25,
        classes=("pattern_a", "pattern_b", "pattern_c"),
        mmrotate_batch_size=4,
        mmrotate_workers=8,
        mmrotate_amp=True,
    )

    assert "train_dataloader = dict(" in config_text
    assert "val_dataloader = dict(" in config_text
    assert "test_dataloader = dict(" in config_text
    assert "custom_imports = dict(" in config_text
    assert "obb_baseline.metrics_mmrotate" in config_text
    assert "ann_file='train/labelTxt/'" in config_text
    assert "ann_file='val/labelTxt/'" in config_text
    assert "ann_file='test/labelTxt/'" in config_text
    assert "img_path='train/images/'" in config_text
    assert "img_path='val/images/'" in config_text
    assert "img_path='test/images/'" in config_text
    assert "val_evaluator = dict(" in config_text
    assert "type='BenchmarkDOTAMetric'" in config_text
    assert "metric='mAP'" in config_text
    assert "score_thr=score_thr" in config_text
    assert "iou_thrs=[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]" in config_text
    assert "test_evaluator = val_evaluator" in config_text
    assert "default_hooks = dict(" in config_text
    assert "checkpoint=dict(" in config_text
    assert "interval=-1" in config_text
    assert "save_last=True" in config_text
    assert "save_best='dota/mAP'" in config_text
    assert "rule='greater'" in config_text
    assert "max_keep_ckpts=1" in config_text


def test_render_mmrotate_config_defaults_mmrotate_epochs(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import _parse_generated_config, render_mmrotate_config

    generated_config = tmp_path / "mmrotate.generated.py"
    generated_config.write_text(
        render_mmrotate_config(
            model_name="oriented_rcnn_r50",
            data_root=tmp_path / "views" / "dota" / "split-11",
            work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
            train_seed=101,
            score_thr=0.25,
            classes=("pattern_a", "pattern_b", "pattern_c"),
        ),
        encoding="utf-8",
    )

    assert "mmrotate_epochs = 36" in generated_config.read_text(encoding="utf-8")

    parsed = _parse_generated_config(generated_config)
    assert parsed["mmrotate_epochs"] == 36


def test_render_mmrotate_config_supports_stage3_runtime_presets(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import _parse_generated_config, render_mmrotate_config

    generated_config = tmp_path / "mmrotate.generated.py"
    generated_config.write_text(
        render_mmrotate_config(
            model_name="oriented_rcnn_r50",
            data_root=tmp_path / "views" / "dota" / "split-11",
            work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
            train_seed=101,
            score_thr=0.25,
            classes=("pattern_a", "pattern_b", "pattern_c"),
            mmrotate_train_aug_preset="spectrogram_v1",
            mmrotate_anchor_ratio_preset="slender_v1",
            mmrotate_roi_bbox_loss_preset="gwd",
        ),
        encoding="utf-8",
    )

    text = generated_config.read_text(encoding="utf-8")
    assert 'mmrotate_train_aug_preset = "spectrogram_v1"' in text
    assert 'mmrotate_anchor_ratio_preset = "slender_v1"' in text
    assert 'mmrotate_roi_bbox_loss_preset = "gwd"' in text

    parsed = _parse_generated_config(generated_config)
    assert parsed["mmrotate_train_aug_preset"] == "spectrogram_v1"
    assert parsed["mmrotate_anchor_ratio_preset"] == "slender_v1"
    assert parsed["mmrotate_roi_bbox_loss_preset"] == "gwd"


def test_render_mmrotate_config_supports_boundary_aux_preset(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import _parse_generated_config, render_mmrotate_config

    generated_config = tmp_path / "mmrotate.generated.py"
    generated_config.write_text(
        render_mmrotate_config(
            model_name="oriented_rcnn_r50",
            data_root=tmp_path / "views" / "dota" / "split-11",
            work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
            train_seed=101,
            score_thr=0.25,
            classes=("pattern_a",),
            mmrotate_boundary_aux_preset="boundary_v1",
        ),
        encoding="utf-8",
    )

    text = generated_config.read_text(encoding="utf-8")
    assert 'mmrotate_boundary_aux_preset = "boundary_v1"' in text
    parsed = _parse_generated_config(generated_config)
    assert parsed["mmrotate_boundary_aux_preset"] == "boundary_v1"


def test_render_mmrotate_config_supports_topology_aux_preset(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import _parse_generated_config, render_mmrotate_config

    generated_config = tmp_path / "mmrotate.generated.py"
    generated_config.write_text(
        render_mmrotate_config(
            model_name="oriented_rcnn_r50",
            data_root=tmp_path / "views" / "dota" / "split-11",
            work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
            train_seed=101,
            score_thr=0.25,
            classes=("pattern_a",),
            mmrotate_topology_aux_preset="topology_v1",
        ),
        encoding="utf-8",
    )

    text = generated_config.read_text(encoding="utf-8")
    assert 'mmrotate_topology_aux_preset = "topology_v1"' in text
    parsed = _parse_generated_config(generated_config)
    assert parsed["mmrotate_topology_aux_preset"] == "topology_v1"


def test_apply_runtime_overrides_keeps_amp_disabled_and_workers_zero_nonpersistent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "train_dataloader": {
            "batch_size": 2,
            "num_workers": 2,
            "persistent_workers": True,
            "pin_memory": True,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "val_dataloader": {
            "num_workers": 1,
            "persistent_workers": True,
            "pin_memory": True,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "test_dataloader": {
            "num_workers": 1,
            "persistent_workers": True,
            "pin_memory": True,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "model": {
            "roi_head": {"bbox_head": {"num_classes": 15}},
            "test_cfg": {"rcnn": {"score_thr": 0.5}},
        },
        "optim_wrapper": {
            "type": "OptimWrapper",
            "optimizer": {"type": "SGD", "lr": 0.01},
        },
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b", "pattern_c"),
            "num_classes": 3,
            "score_thr": 0.25,
            "mmrotate_batch_size": 2,
            "mmrotate_workers": 0,
            "mmrotate_amp": False,
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cpu",
    )

    assert cfg["train_dataloader"]["num_workers"] == 0
    assert cfg["val_dataloader"]["num_workers"] == 0
    assert cfg["test_dataloader"]["num_workers"] == 0
    assert cfg["train_dataloader"]["persistent_workers"] is False


def test_apply_runtime_overrides_supports_orcnn_stage3_presets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "train_dataloader": {
            "dataset": {
                "pipeline": [
                    {"type": "mmdet.LoadImageFromFile"},
                    {"type": "mmdet.LoadAnnotations"},
                    {"type": "mmdet.RandomFlip", "prob": 0.75, "direction": ["horizontal", "vertical", "diagonal"]},
                    {"type": "mmdet.PackDetInputs"},
                ]
            }
        },
        "val_dataloader": {"dataset": {"pipeline": []}},
        "test_dataloader": {"dataset": {"pipeline": []}},
        "model": {
            "rpn_head": {
                "anchor_generator": {"ratios": [0.5, 1.0, 2.0]},
            },
            "roi_head": {
                "bbox_head": {
                    "reg_decoded_bbox": False,
                    "loss_bbox": {"type": "mmdet.SmoothL1Loss", "beta": 1.0, "loss_weight": 1.0},
                }
            },
        },
        "optim_wrapper": {"type": "OptimWrapper", "optimizer": {"type": "SGD", "lr": 0.01}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a",),
            "num_classes": 1,
            "score_thr": 0.25,
            "mmrotate_batch_size": 2,
            "mmrotate_workers": 0,
            "mmrotate_amp": False,
            "mmrotate_train_aug_preset": "spectrogram_v1",
            "mmrotate_anchor_ratio_preset": "slender_v1",
            "mmrotate_roi_bbox_loss_preset": "gwd",
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cpu",
    )

    train_pipeline = cfg["train_dataloader"]["dataset"]["pipeline"]
    assert all(step.get("type") != "mmdet.RandomFlip" for step in train_pipeline)
    assert cfg["model"]["rpn_head"]["anchor_generator"]["ratios"] == [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    assert cfg["model"]["roi_head"]["bbox_head"]["reg_decoded_bbox"] is True
    assert cfg["model"]["roi_head"]["bbox_head"]["loss_bbox"]["type"] == "GDLoss"
    assert cfg["model"]["roi_head"]["bbox_head"]["loss_bbox"]["loss_type"] == "gwd"


def test_apply_runtime_overrides_supports_boundary_aux_preset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "model": {
            "roi_head": {
                "type": "OrientedStandardRoIHead",
                "bbox_head": {
                    "type": "RotatedShared2FCBBoxHead",
                },
            },
        },
        "optim_wrapper": {"type": "OptimWrapper", "optimizer": {"type": "SGD", "lr": 0.01}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "class_names": ("pattern_a",),
            "num_classes": 1,
            "mmrotate_boundary_aux_preset": "boundary_v1",
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cpu",
    )

    assert cfg["model"]["roi_head"]["type"] == "OrientedBoundaryAuxRoIHead"
    assert cfg["model"]["roi_head"]["bbox_head"]["type"] == "OrientedBoundaryAuxBBoxHead"
    assert cfg["model"]["roi_head"]["bbox_head"]["boundary_aux_loss_weight"] == 0.2
    assert cfg["optim_wrapper"]["type"] == "OptimWrapper"
    assert "loss_scale" not in cfg["optim_wrapper"]


def test_apply_runtime_overrides_supports_topology_aux_preset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "model": {
            "roi_head": {
                "type": "OrientedStandardRoIHead",
                "bbox_head": {
                    "type": "RotatedShared2FCBBoxHead",
                },
            },
        },
        "optim_wrapper": {"type": "OptimWrapper", "optimizer": {"type": "SGD", "lr": 0.01}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "class_names": ("pattern_a",),
            "num_classes": 1,
            "mmrotate_topology_aux_preset": "topology_v1",
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cpu",
    )

    assert cfg["model"]["roi_head"]["type"] == "OrientedBoundaryAuxRoIHead"
    assert cfg["model"]["roi_head"]["bbox_head"]["type"] == "OrientedBoundaryAuxBBoxHead"
    assert cfg["model"]["roi_head"]["bbox_head"]["topology_aux_loss_weight"] == 0.1
    assert cfg["model"]["roi_head"]["bbox_head"]["centerline_width"] == 1


def test_apply_runtime_overrides_scales_scheduler_epochs(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    cfg = {
        "train_cfg": {"max_epochs": 24},
        "param_scheduler": [
            {"type": "CosineAnnealingLR", "end": 24},
            {"type": "MultiStepLR", "milestones": [8, 16]},
            {"type": "ReduceLROnPlateau", "milestones": (6, 12)},
        ],
        "model": {"roi_head": {"bbox_head": {"num_classes": 15}}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "mmrotate_epochs": 36,
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b"),
            "num_classes": 2,
            "score_thr": 0.5,
        },
        work_dir=tmp_path / "workdir",
        train_seed=42,
        device="cpu",
    )

    assert cfg["train_cfg"]["max_epochs"] == 36
    assert cfg["param_scheduler"][0]["end"] == 36
    assert cfg["param_scheduler"][1]["milestones"] == [12, 24]
    assert cfg["param_scheduler"][2]["milestones"] == (9, 18)


def test_parse_generated_config_accepts_rendered_mmrotate_contract(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _parse_generated_config, render_mmrotate_config

    generated_config = tmp_path / "mmrotate.generated.py"
    generated_config.write_text(
        render_mmrotate_config(
            model_name="oriented_rcnn_r50",
            data_root=tmp_path / "views" / "dota" / "split-11",
            work_dir=tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101",
            train_seed=101,
            score_thr=0.25,
            classes=("pattern_a", "pattern_b", "pattern_c"),
            mmrotate_batch_size=4,
            mmrotate_workers=8,
            mmrotate_amp=True,
        ),
        encoding="utf-8",
    )

    parsed = _parse_generated_config(generated_config)

    assert parsed == {
        "preset": "oriented_rcnn",
        "classes": ("pattern_a", "pattern_b", "pattern_c"),
        "class_names": ("pattern_a", "pattern_b", "pattern_c"),
        "num_classes": 3,
        "data_root": f'{(tmp_path / "views" / "dota" / "split-11").as_posix()}/',
        "work_dir": (tmp_path / "workdirs" / "oriented_rcnn_r50" / "split-11" / "seed-101").as_posix(),
        "train_seed": 101,
        "score_thr": 0.25,
        "mmrotate_batch_size": 4,
        "mmrotate_workers": 8,
        "mmrotate_amp": True,
        "mmrotate_epochs": 36,
        "mmrotate_train_aug_preset": "default",
        "mmrotate_anchor_ratio_preset": "default",
        "mmrotate_roi_bbox_loss_preset": "smooth_l1",
        "mmrotate_boundary_aux_preset": "none",
        "mmrotate_topology_aux_preset": "none",
    }


def test_apply_runtime_overrides_updates_mmrotate_batch_workers_and_amp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "train_dataloader": {
            "batch_size": 2,
            "num_workers": 2,
            "persistent_workers": True,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "val_dataloader": {
            "num_workers": 1,
            "persistent_workers": False,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "test_dataloader": {
            "num_workers": 1,
            "persistent_workers": False,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "model": {
            "roi_head": {"bbox_head": {"num_classes": 15}},
            "test_cfg": {"rcnn": {"score_thr": 0.5}},
        },
        "optim_wrapper": {
            "type": "OptimWrapper",
            "optimizer": {"type": "SGD", "lr": 0.01},
        },
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b", "pattern_c"),
            "num_classes": 3,
            "score_thr": 0.25,
            "mmrotate_batch_size": 4,
            "mmrotate_workers": 8,
            "mmrotate_amp": True,
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cuda:0",
    )

    assert cfg["train_dataloader"]["batch_size"] == 4
    assert cfg["train_dataloader"]["num_workers"] == 8
    assert cfg["val_dataloader"]["num_workers"] == 8
    assert cfg["test_dataloader"]["num_workers"] == 8
    assert cfg["train_dataloader"]["persistent_workers"] is True
    assert cfg["val_dataloader"]["persistent_workers"] is True
    assert cfg["test_dataloader"]["persistent_workers"] is True
    assert cfg["train_dataloader"]["pin_memory"] is True
    assert cfg["val_dataloader"]["pin_memory"] is True
    assert cfg["test_dataloader"]["pin_memory"] is True
    assert cfg["optim_wrapper"]["type"] == "AmpOptimWrapper"
    assert cfg["optim_wrapper"]["loss_scale"] == "dynamic"
    assert cfg["randomness"] == {"seed": 101}
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"


def test_apply_runtime_overrides_disables_amp_for_r3det(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    cfg = {
        "train_dataloader": {
            "batch_size": 2,
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "val_dataloader": {
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "test_dataloader": {
            "dataset": {"data_root": "old", "metainfo": {"classes": ("old",)}},
        },
        "model": {
            "bbox_head_refine": [{"num_classes": 15}],
            "test_cfg": {"score_thr": 0.5},
        },
        "optim_wrapper": {
            "type": "OptimWrapper",
            "optimizer": {"type": "SGD", "lr": 0.01},
        },
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "preset": "r3det",
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b", "pattern_c"),
            "num_classes": 3,
            "score_thr": 0.25,
            "mmrotate_amp": True,
        },
        work_dir=tmp_path / "workdir",
        train_seed=101,
        device="cuda:0",
    )

    assert cfg["optim_wrapper"]["type"] == "OptimWrapper"
    assert "loss_scale" not in cfg["optim_wrapper"]
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"


def test_apply_runtime_overrides_downscales_scheduler_begin_end_and_tmax(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    cfg = {
        "train_cfg": {"max_epochs": 36},
        "param_scheduler": [
            {
                "type": "LinearLR",
                "by_epoch": False,
                "begin": 0,
                "end": 1000,
            },
            {
                "type": "CosineAnnealingLR",
                "begin": 18,
                "end": 36,
                "T_max": 18,
                "by_epoch": True,
                "convert_to_iter_based": True,
            },
        ],
        "model": {"bbox_head": {"num_classes": 15}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "preset": "rtmdet_rotated",
            "mmrotate_epochs": 2,
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b"),
            "num_classes": 2,
            "score_thr": 0.5,
        },
        work_dir=tmp_path / "workdir",
        train_seed=42,
        device="cpu",
    )

    assert cfg["train_cfg"]["max_epochs"] == 2
    assert cfg["param_scheduler"][0]["begin"] == 0
    assert cfg["param_scheduler"][0]["end"] == 56
    assert cfg["param_scheduler"][1]["begin"] == 1
    assert cfg["param_scheduler"][1]["end"] == 2
    assert cfg["param_scheduler"][1]["T_max"] == 1


def test_apply_runtime_overrides_keeps_scheduler_begin_strictly_less_than_end(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import _apply_runtime_overrides

    cfg = {
        "train_cfg": {"max_epochs": 36},
        "param_scheduler": [
            {
                "type": "CosineAnnealingLR",
                "begin": 18,
                "end": 36,
                "T_max": 18,
                "by_epoch": True,
            }
        ],
        "model": {"bbox_head": {"num_classes": 15}},
    }

    _apply_runtime_overrides(
        cfg,
        parsed_generated_config={
            "preset": "rtmdet_rotated",
            "mmrotate_epochs": 1,
            "data_root": f"{tmp_path.as_posix()}/",
            "class_names": ("pattern_a", "pattern_b"),
            "num_classes": 2,
            "score_thr": 0.5,
        },
        work_dir=tmp_path / "workdir",
        train_seed=42,
        device="cpu",
    )

    assert cfg["train_cfg"]["max_epochs"] == 1
    assert cfg["param_scheduler"][0]["begin"] == 0
    assert cfg["param_scheduler"][0]["end"] == 1
    assert cfg["param_scheduler"][0]["T_max"] == 1


def test_normalize_mmrotate_metrics_maps_dota_keys_and_computes_f1() -> None:
    from obb_baseline.runners_mmrotate import normalize_mmrotate_metrics

    metrics = normalize_mmrotate_metrics(
        {
            "dota/AP50": 0.62,
            "dota/mAP": "0.41",
            "dota/precision": 0.8,
            "dota/recall": "0.5",
        }
    )

    assert metrics == {
        "mAP50_95": 0.41,
        "mAP50": 0.62,
        "precision": 0.8,
        "recall": 0.5,
        "f1": pytest.approx(2 * 0.8 * 0.5 / (0.8 + 0.5), abs=1e-6),
    }


def test_write_mmrotate_metrics_json_writes_full_metric_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline.runners_mmrotate import (
        RunMetadata,
        write_mmrotate_metrics_json,
    )

    signature = inspect.signature(write_mmrotate_metrics_json)
    assert "normalized_metrics" in signature.parameters
    assert "metrics" not in signature.parameters

    def _should_not_be_called(_: object) -> dict[str, float | None]:
        raise AssertionError("writer should not call normalize_mmrotate_metrics")

    monkeypatch.setattr(
        "obb_baseline.runners_mmrotate.normalize_mmrotate_metrics",
        _should_not_be_called,
    )

    metrics_path = tmp_path / "metrics.json"
    write_mmrotate_metrics_json(
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="oriented_rcnn_r50",
            preset="oriented-rcnn-r50-fpn",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={
                "config": "configs/oriented_rcnn.py",
                "best_checkpoint": "checkpoints/best.pth",
            },
            train_time_sec=123.4,
            infer_time_ms=7.8,
            peak_mem_mb=4096.0,
            param_count=20500000,
            checkpoint_size_mb=82.1,
        ),
        status="succeeded",
        normalized_metrics={
            "mAP50_95": "keep-this-raw",
            "mAP50": 0.62,
            "precision": 0.8,
            "recall": 0.5,
            "f1": 0.615384,
        },
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "benchmark_name",
        "split_manifest_hash",
        "model_name",
        "preset",
        "holdout_seed",
        "split_seed",
        "train_seed",
        "status",
        "mAP50_95",
        "mAP50",
        "precision",
        "recall",
        "f1",
        "train_time_sec",
        "infer_time_ms",
        "peak_mem_mb",
        "param_count",
        "checkpoint_size_mb",
        "artifact_paths",
    }
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["split_manifest_hash"] == "abc123"
    assert payload["model_name"] == "oriented_rcnn_r50"
    assert payload["preset"] == "oriented-rcnn-r50-fpn"
    assert payload["holdout_seed"] == 3407
    assert payload["split_seed"] == 11
    assert payload["train_seed"] == 101
    assert payload["status"] == "succeeded"
    assert payload["mAP50_95"] == "keep-this-raw"
    assert payload["mAP50"] == 0.62
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.5
    assert payload["f1"] == 0.615384
    assert payload["train_time_sec"] == 123.4
    assert payload["infer_time_ms"] == 7.8
    assert payload["peak_mem_mb"] == 4096.0
    assert payload["param_count"] == 20500000
    assert payload["checkpoint_size_mb"] == 82.1
    assert payload["artifact_paths"] == {
        "config": "configs/oriented_rcnn.py",
        "best_checkpoint": "checkpoints/best.pth",
    }


def test_parse_mmrotate_outputs_reads_raw_files_and_writes_metrics(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import RunMetadata, parse_mmrotate_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "raw_metrics.json").write_text(
        json.dumps(
            {
                "dota/mAP": 0.42,
                "dota/AP50": 0.66,
                "precision": 0.8,
                "recall": 0.5,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (work_dir / "artifacts.json").write_text(
        json.dumps({"best_checkpoint": "epoch_12.pth"}, ensure_ascii=False),
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_mmrotate_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="oriented_rcnn_r50",
            preset="oriented-rcnn-r50-fpn",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="succeeded",
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["mAP50_95"] == 0.42
    assert payload["mAP50"] == 0.66
    assert payload["artifact_paths"]["best_checkpoint"] == "epoch_12.pth"
    assert payload["artifact_paths"]["raw_metrics"] == str(work_dir / "raw_metrics.json")
    assert payload["artifact_paths"]["artifacts_json"] == str(work_dir / "artifacts.json")


def test_parse_mmrotate_outputs_writes_failed_metrics_when_execution_failed(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import RunMetadata, parse_mmrotate_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "raw_metrics.json").write_text(
        json.dumps({"dota/mAP": 0.99}, ensure_ascii=False),
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_mmrotate_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="oriented_rcnn_r50",
            preset="oriented-rcnn-r50-fpn",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="failed",
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["mAP50_95"] is None
    assert payload["mAP50"] is None
    assert payload["precision"] is None
    assert payload["recall"] is None
    assert payload["f1"] is None


def test_main_executes_pipeline_and_writes_stable_raw_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        (
            'preset = "oriented_rcnn"\n'
            "classes = ('plane', 'ship')\n"
            "class_names = classes\n"
            "num_classes = len(classes)\n"
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"

    captured: dict[str, object] = {}

    def _fake_execute(
        *,
        generated_config: Path,
        parsed_generated_config: dict[str, object],
        work_dir: Path,
        train_seed: int,
        device: str,
    ) -> dict[str, dict[str, object]]:
        captured["generated_config"] = generated_config
        captured["parsed_generated_config"] = parsed_generated_config
        captured["work_dir"] = work_dir
        captured["train_seed"] = train_seed
        captured["device"] = device
        return {
            "raw_metrics": {"dota/mAP": 0.42, "dota/AP50": 0.66},
            "artifacts": {"best_checkpoint": "epoch_12.pth"},
        }

    monkeypatch.setattr(module, "_execute_mmrotate_pipeline", _fake_execute)

    exit_code = module.main(
        [
            "--config",
            str(generated_config),
            "--work-dir",
            str(work_dir),
            "--seed",
            "101",
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 0
    assert captured["generated_config"] == generated_config
    assert captured["work_dir"] == work_dir
    assert captured["train_seed"] == 101
    assert captured["device"] == "cpu"
    assert captured["parsed_generated_config"] == {
        "preset": "oriented_rcnn",
        "classes": ("plane", "ship"),
        "class_names": ("plane", "ship"),
        "num_classes": 2,
    }

    raw_metrics_path = work_dir / "raw_metrics.json"
    artifacts_path = work_dir / "artifacts.json"
    assert raw_metrics_path.exists()
    assert artifacts_path.exists()
    assert json.loads(raw_metrics_path.read_text(encoding="utf-8")) == {"dota/mAP": 0.42, "dota/AP50": 0.66}
    assert json.loads(artifacts_path.read_text(encoding="utf-8")) == {"best_checkpoint": "epoch_12.pth"}


def test_main_writes_raw_outputs_with_numpy_like_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    class FakeScalar:
        def __init__(self, value: object) -> None:
            self.value = value

        def item(self) -> object:
            return self.value

    class FakeArray:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def tolist(self) -> list[object]:
            return list(self.values)

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        (
            'preset = "oriented_rcnn"\n'
            "classes = ('plane', 'ship')\n"
            "class_names = classes\n"
            "num_classes = len(classes)\n"
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"

    def _fake_execute(
        *,
        generated_config: Path,
        parsed_generated_config: dict[str, object],
        work_dir: Path,
        train_seed: int,
        device: str,
    ) -> dict[str, dict[str, object]]:
        _ = (
            generated_config,
            parsed_generated_config,
            work_dir,
            train_seed,
            device,
        )
        return {
            "raw_metrics": {
                "dota/mAP": FakeScalar(0.42),
                "curve": FakeArray([FakeScalar(1), FakeScalar(2)]),
                "summary_path": Path("metrics/summary.txt"),
                "scores": (FakeScalar(0.1), FakeScalar(0.2)),
            },
            "artifacts": {
                "best_checkpoint": Path("epoch_12.pth"),
                "history": FakeArray([FakeScalar(3), FakeScalar(4)]),
            },
        }

    monkeypatch.setattr(module, "_execute_mmrotate_pipeline", _fake_execute)

    exit_code = module.main(
        [
            "--config",
            str(generated_config),
            "--work-dir",
            str(work_dir),
            "--seed",
            "101",
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 0
    raw_metrics_path = work_dir / "raw_metrics.json"
    artifacts_path = work_dir / "artifacts.json"
    assert json.loads(raw_metrics_path.read_text(encoding="utf-8")) == {
        "dota/mAP": 0.42,
        "curve": [1, 2],
        "summary_path": "metrics/summary.txt",
        "scores": [0.1, 0.2],
    }
    assert json.loads(artifacts_path.read_text(encoding="utf-8")) == {
        "best_checkpoint": "epoch_12.pth",
        "history": [3, 4],
    }


def test_execute_mmrotate_pipeline_tests_with_best_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        "preset = 'oriented_rcnn'\n",
        encoding="utf-8",
    )
    work_dir = tmp_path / "workdir"
    work_dir.mkdir(parents=True, exist_ok=True)
    best_checkpoint = work_dir / "best_bbox_mAP_epoch_2.pth"
    best_checkpoint.write_text("stub", encoding="utf-8")
    (work_dir / "last_checkpoint").write_text(str(work_dir / "epoch_2.pth"), encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self) -> None:
            self.model = object()

        def train(self) -> None:
            captured["train_called"] = True

        def test(self) -> dict[str, float]:
            captured["test_called"] = True
            return {"dota/mAP": 0.42}

    fake_runner = FakeRunner()

    class FakeRunnerFactory:
        @staticmethod
        def from_cfg(cfg: object) -> FakeRunner:
            captured["runner_cfg"] = cfg
            return fake_runner

    class FakeConfig:
        @staticmethod
        def fromfile(path: str) -> dict[str, object]:
            captured["config_path"] = path
            return {}

    mmengine_module = ModuleType("mmengine")
    mmengine_config = ModuleType("mmengine.config")
    mmengine_config.Config = FakeConfig
    mmengine_registry = ModuleType("mmengine.registry")
    mmengine_registry.init_default_scope = lambda scope: captured.setdefault("scope", scope)
    mmengine_runner = ModuleType("mmengine.runner")
    mmengine_runner.Runner = FakeRunnerFactory

    def _fake_load_checkpoint(model: object, filename: str, map_location: str = "cpu") -> dict[str, str]:
        captured["loaded_model"] = model
        captured["loaded_checkpoint"] = filename
        captured["map_location"] = map_location
        return {"meta": "ok"}

    mmengine_runner_checkpoint = ModuleType("mmengine.runner.checkpoint")
    mmengine_runner_checkpoint.load_checkpoint = _fake_load_checkpoint

    monkeypatch.setitem(sys.modules, "mmengine", mmengine_module)
    monkeypatch.setitem(sys.modules, "mmengine.config", mmengine_config)
    monkeypatch.setitem(sys.modules, "mmengine.registry", mmengine_registry)
    monkeypatch.setitem(sys.modules, "mmengine.runner", mmengine_runner)
    monkeypatch.setitem(sys.modules, "mmengine.runner.checkpoint", mmengine_runner_checkpoint)
    monkeypatch.setattr(module, "_apply_runtime_overrides", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_apply_python_compat_shims", lambda: None)

    result = module._execute_mmrotate_pipeline(
        generated_config=generated_config,
        parsed_generated_config={},
        work_dir=work_dir,
        train_seed=101,
        device="cpu",
    )

    assert captured["train_called"] is True
    assert captured["loaded_checkpoint"] == str(best_checkpoint)
    assert captured["loaded_model"] is fake_runner.model
    assert captured["test_called"] is True
    assert result["raw_metrics"] == {"dota/mAP": 0.42}
    assert result["artifacts"]["best_checkpoint"] == str(best_checkpoint)


def test_execute_mmrotate_pipeline_falls_back_to_last_checkpoint_for_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        "preset = 'oriented_rcnn'\n",
        encoding="utf-8",
    )
    work_dir = tmp_path / "workdir"
    work_dir.mkdir(parents=True, exist_ok=True)
    last_checkpoint = work_dir / "epoch_2.pth"
    last_checkpoint.write_text("stub", encoding="utf-8")
    (work_dir / "last_checkpoint").write_text(str(last_checkpoint), encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self) -> None:
            self.model = object()

        def train(self) -> None:
            captured["train_called"] = True

        def test(self) -> dict[str, float]:
            captured["test_called"] = True
            return {"dota/mAP": 0.24}

    fake_runner = FakeRunner()

    class FakeRunnerFactory:
        @staticmethod
        def from_cfg(cfg: object) -> FakeRunner:
            return fake_runner

    class FakeConfig:
        @staticmethod
        def fromfile(path: str) -> dict[str, object]:
            return {}

    mmengine_module = ModuleType("mmengine")
    mmengine_config = ModuleType("mmengine.config")
    mmengine_config.Config = FakeConfig
    mmengine_registry = ModuleType("mmengine.registry")
    mmengine_registry.init_default_scope = lambda scope: None
    mmengine_runner = ModuleType("mmengine.runner")
    mmengine_runner.Runner = FakeRunnerFactory

    def _fake_load_checkpoint(model: object, filename: str, map_location: str = "cpu") -> dict[str, str]:
        captured["loaded_checkpoint"] = filename
        return {"meta": "ok"}

    mmengine_runner_checkpoint = ModuleType("mmengine.runner.checkpoint")
    mmengine_runner_checkpoint.load_checkpoint = _fake_load_checkpoint

    monkeypatch.setitem(sys.modules, "mmengine", mmengine_module)
    monkeypatch.setitem(sys.modules, "mmengine.config", mmengine_config)
    monkeypatch.setitem(sys.modules, "mmengine.registry", mmengine_registry)
    monkeypatch.setitem(sys.modules, "mmengine.runner", mmengine_runner)
    monkeypatch.setitem(sys.modules, "mmengine.runner.checkpoint", mmengine_runner_checkpoint)
    monkeypatch.setattr(module, "_apply_runtime_overrides", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_apply_python_compat_shims", lambda: None)

    result = module._execute_mmrotate_pipeline(
        generated_config=generated_config,
        parsed_generated_config={},
        work_dir=work_dir,
        train_seed=101,
        device="cpu",
    )

    assert captured["train_called"] is True
    assert captured["loaded_checkpoint"] == str(last_checkpoint)
    assert captured["test_called"] is True
    assert result["raw_metrics"] == {"dota/mAP": 0.24}
