from __future__ import annotations

"""MMRotate 运行时配置生成器。

为什么用“动态生成配置文件”：
1. 项目标签集合是运行时决定的，`num_classes` 必须动态注入。
2. 数据目录是 step workspace 隔离路径，不能写死在静态 cfg。
3. 通过写入最终 cfg 文件，可以把“真实训练参数”完整固化，便于复现。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class PresetSpec:
    preset_id: str
    checkpoint: str


PRESET_SPECS: dict[str, PresetSpec] = {
    "oriented-rcnn-le90_r50_fpn_1x_dota": PresetSpec(
        preset_id="oriented-rcnn-le90_r50_fpn_1x_dota",
        checkpoint=(
            "https://mmassets.onedl.ai/mmrotate/v0.1.0/oriented_rcnn/"
            "oriented_rcnn_r50_fpn_1x_dota_le90/"
            "oriented_rcnn_r50_fpn_1x_dota_le90-6d2b2ce0.pth"
        ),
    )
}


def resolve_preset_checkpoint(preset_id: str) -> str:
    spec = PRESET_SPECS.get(str(preset_id or "").strip())
    if spec is None:
        raise ValueError(f"unsupported preset: {preset_id!r}")
    return spec.checkpoint


def build_mmrotate_runtime_cfg(
    *,
    output_path: Path,
    data_root: Path,
    classes: Sequence[str],
    epochs: int,
    batch: int,
    workers: int,
    imgsz: int,
    nms_iou_thr: float,
    max_per_img: int,
    val_degraded: bool,
    work_dir: Path,
    load_from: str,
    train_seed: int,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 关键设计：
    # 1. iou_thrs 使用 0.50~0.95，直接支撑 map50_95 的精确计算。
    # 2. val_degraded 时把 val 指到 train，保证小样本项目也可执行 eval。
    # 3. default_scope 固定 mmrotate，确保 registry 能找到旋转检测组件。
    iou_thrs = [round(0.5 + i * 0.05, 2) for i in range(10)]
    milestones = sorted({max(1, int(epochs * 0.66)), max(1, int(epochs * 0.9))})
    classes_text = repr(tuple(str(v) for v in classes))

    val_ann = "train/labelTxt" if val_degraded else "val/labelTxt"
    val_img = "train/images" if val_degraded else "val/images"

    cfg_text = f'''# -*- coding: utf-8 -*-
# 该文件由 saki-plugin-oriented-rcnn 自动生成。
# 修改请回到插件代码生成逻辑，避免手改后被下一轮覆盖。

default_scope = "mmrotate"

custom_imports = dict(imports=["mmrotate"], allow_failed_imports=False)

classes = {classes_text}
metainfo = dict(classes=classes)

dataset_type = "DOTADataset"
data_root = r"{data_root.as_posix()}/"

train_pipeline = [
    dict(type="mmdet.LoadImageFromFile"),
    dict(type="mmdet.LoadAnnotations", with_bbox=True, box_type="qbox"),
    dict(type="ConvertBoxType", box_type_mapping=dict(gt_bboxes="rbox")),
    dict(type="mmdet.Resize", scale=({int(imgsz)}, {int(imgsz)}), keep_ratio=True),
    dict(type="mmdet.RandomFlip", prob=0.75, direction=["horizontal", "vertical", "diagonal"]),
    dict(type="mmdet.PackDetInputs"),
]

val_pipeline = [
    dict(type="mmdet.LoadImageFromFile"),
    dict(type="mmdet.Resize", scale=({int(imgsz)}, {int(imgsz)}), keep_ratio=True),
    dict(type="mmdet.LoadAnnotations", with_bbox=True, box_type="qbox"),
    dict(type="ConvertBoxType", box_type_mapping=dict(gt_bboxes="rbox")),
    dict(type="mmdet.PackDetInputs", meta_keys=("img_id", "img_path", "ori_shape", "img_shape", "scale_factor")),
]

train_dataloader = dict(
    batch_size={int(batch)},
    num_workers={int(workers)},
    persistent_workers={"True" if int(workers) > 0 else "False"},
    sampler=dict(type="DefaultSampler", shuffle=True),
    batch_sampler=None,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file="train/labelTxt",
        data_prefix=dict(img_path="train/images"),
        metainfo=metainfo,
        img_suffix="png",
        filter_cfg=dict(filter_empty_gt=True),
        pipeline=train_pipeline,
    ),
)

val_dataloader = dict(
    batch_size=1,
    num_workers={int(workers)},
    persistent_workers={"True" if int(workers) > 0 else "False"},
    drop_last=False,
    sampler=dict(type="DefaultSampler", shuffle=False),
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file="{val_ann}",
        data_prefix=dict(img_path="{val_img}"),
        metainfo=metainfo,
        img_suffix="png",
        test_mode=True,
        pipeline=val_pipeline,
    ),
)

test_dataloader = val_dataloader

val_evaluator = dict(type="DOTAMetric", metric="mAP", iou_thrs={repr(iou_thrs)})
test_evaluator = val_evaluator

angle_version = "le90"
model = dict(
    type="mmdet.FasterRCNN",
    data_preprocessor=dict(
        type="mmdet.DetDataPreprocessor",
        mean=[123.675, 116.28, 103.53],
        std=[58.395, 57.12, 57.375],
        bgr_to_rgb=True,
        pad_size_divisor=32,
        boxtype2tensor=False,
    ),
    backbone=dict(
        type="mmdet.ResNet",
        depth=50,
        num_stages=4,
        out_indices=(0, 1, 2, 3),
        frozen_stages=1,
        norm_cfg=dict(type="BN", requires_grad=True),
        norm_eval=True,
        style="pytorch",
        init_cfg=dict(type="Pretrained", checkpoint="torchvision://resnet50"),
    ),
    neck=dict(type="mmdet.FPN", in_channels=[256, 512, 1024, 2048], out_channels=256, num_outs=5),
    rpn_head=dict(
        type="OrientedRPNHead",
        in_channels=256,
        feat_channels=256,
        anchor_generator=dict(type="mmdet.AnchorGenerator", scales=[8], ratios=[0.5, 1.0, 2.0], strides=[4, 8, 16, 32, 64], use_box_type=True),
        bbox_coder=dict(type="MidpointOffsetCoder", angle_version=angle_version, target_means=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], target_stds=[1.0, 1.0, 1.0, 1.0, 0.5, 0.5]),
        loss_cls=dict(type="mmdet.CrossEntropyLoss", use_sigmoid=True, loss_weight=1.0),
        loss_bbox=dict(type="mmdet.SmoothL1Loss", beta=0.1111111111111111, loss_weight=1.0),
    ),
    roi_head=dict(
        type="mmdet.StandardRoIHead",
        bbox_roi_extractor=dict(
            type="RotatedSingleRoIExtractor",
            roi_layer=dict(type="RoIAlignRotated", out_size=7, sample_num=2, clockwise=True),
            out_channels=256,
            featmap_strides=[4, 8, 16, 32],
        ),
        bbox_head=dict(
            type="mmdet.Shared2FCBBoxHead",
            predict_box_type="rbox",
            in_channels=256,
            fc_out_channels=1024,
            roi_feat_size=7,
            num_classes={len(tuple(classes))},
            reg_predictor_cfg=dict(type="mmdet.Linear"),
            cls_predictor_cfg=dict(type="mmdet.Linear"),
            bbox_coder=dict(
                type="DeltaXYWHTRBBoxCoder",
                angle_version=angle_version,
                norm_factor=None,
                edge_swap=True,
                proj_xy=True,
                target_means=(0.0, 0.0, 0.0, 0.0, 0.0),
                target_stds=(0.1, 0.1, 0.2, 0.2, 0.1),
            ),
            reg_class_agnostic=True,
            loss_cls=dict(type="mmdet.CrossEntropyLoss", use_sigmoid=False, loss_weight=1.0),
            loss_bbox=dict(type="mmdet.SmoothL1Loss", beta=1.0, loss_weight=1.0),
        ),
    ),
    train_cfg=dict(
        rpn=dict(
            assigner=dict(type="mmdet.MaxIoUAssigner", pos_iou_thr=0.7, neg_iou_thr=0.3, min_pos_iou=0.3, match_low_quality=True, ignore_iof_thr=-1, iou_calculator=dict(type="RBbox2HBboxOverlaps2D")),
            sampler=dict(type="mmdet.RandomSampler", num=256, pos_fraction=0.5, neg_pos_ub=-1, add_gt_as_proposals=False),
            allowed_border=0,
            pos_weight=-1,
            debug=False,
        ),
        rpn_proposal=dict(nms_pre=2000, max_per_img=2000, nms=dict(type="nms", iou_threshold=0.8), min_bbox_size=0),
        rcnn=dict(
            assigner=dict(type="mmdet.MaxIoUAssigner", pos_iou_thr=0.5, neg_iou_thr=0.5, min_pos_iou=0.5, match_low_quality=False, iou_calculator=dict(type="RBboxOverlaps2D"), ignore_iof_thr=-1),
            sampler=dict(type="mmdet.RandomSampler", num=512, pos_fraction=0.25, neg_pos_ub=-1, add_gt_as_proposals=True),
            pos_weight=-1,
            debug=False,
        ),
    ),
    test_cfg=dict(
        rpn=dict(nms_pre=2000, max_per_img=2000, nms=dict(type="nms", iou_threshold=0.8), min_bbox_size=0),
        rcnn=dict(nms_pre=2000, min_bbox_size=0, score_thr=0.05, nms=dict(type="nms_rotated", iou_threshold={float(nms_iou_thr)}), max_per_img={int(max_per_img)}),
    ),
)

optim_wrapper = dict(type="OptimWrapper", optimizer=dict(type="SGD", lr=0.005, momentum=0.9, weight_decay=0.0001))

param_scheduler = [
    dict(type="LinearLR", begin=0, end=500, by_epoch=False, start_factor=0.001),
    dict(type="MultiStepLR", begin=0, end={int(epochs)}, by_epoch=True, milestones={repr(milestones)}, gamma=0.1),
]

train_cfg = dict(type="EpochBasedTrainLoop", max_epochs={int(epochs)}, val_interval=1)
val_cfg = dict(type="ValLoop")
test_cfg = dict(type="TestLoop")

default_hooks = dict(
    timer=dict(type="IterTimerHook"),
    logger=dict(type="LoggerHook", interval=20),
    param_scheduler=dict(type="ParamSchedulerHook"),
    checkpoint=dict(type="CheckpointHook", interval=1, save_best="dota/mAP", rule="greater", max_keep_ckpts=3),
    sampler_seed=dict(type="DistSamplerSeedHook"),
)

env_cfg = dict(
    cudnn_benchmark=False,
    mp_cfg=dict(mp_start_method="fork", opencv_num_threads=0),
    dist_cfg=dict(backend="nccl"),
)

visualizer = dict(type="mmdet.DetLocalVisualizer", vis_backends=[dict(type="LocalVisBackend")], name="visualizer")
log_processor = dict(type="LogProcessor", window_size=50, by_epoch=True)
log_level = "INFO"
resume = False

work_dir = r"{work_dir.as_posix()}"
load_from = r"{load_from}"

randomness = dict(seed={int(train_seed)}, deterministic=False)
'''
    output_path.write_text(cfg_text, encoding="utf-8")
    return output_path
