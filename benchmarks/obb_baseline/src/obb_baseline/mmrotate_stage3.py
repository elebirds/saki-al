from __future__ import annotations

"""MMRotate stage3 extensions for Oriented R-CNN auxiliary training.

Design goals:
1. Keep inference outputs identical to standard OBB detection.
2. Add training-only boundary and topology supervision branches on RoI features.
3. Derive weak targets directly from OBB geometry; no extra mask labels needed.
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

try:
    from mmcv.runner import force_fp32
except Exception:  # pragma: no cover - runtime compatibility
    def force_fp32(*args, **kwargs):  # type: ignore
        def _decorator(func):
            return func

        return _decorator

try:
    from mmrotate.core import rbbox2roi
    from mmrotate.models.builder import ROTATED_HEADS
    from mmrotate.models.roi_heads.bbox_heads.convfc_rbbox_head import RotatedShared2FCBBoxHead
    from mmrotate.models.roi_heads.oriented_standard_roi_head import OrientedStandardRoIHead
except Exception:  # pragma: no cover - runtime compatibility
    from mmrotate.core import rbbox2roi  # type: ignore
    from mmdet.registry import MODELS as ROTATED_HEADS  # type: ignore
    from mmrotate.models.roi_heads.bbox_heads.convfc_rbbox_head import RotatedShared2FCBBoxHead  # type: ignore
    from mmrotate.models.roi_heads.oriented_standard_roi_head import OrientedStandardRoIHead  # type: ignore


def _obb_to_corners(box: torch.Tensor) -> torch.Tensor:
    cx, cy, w, h, angle = box.unbind()
    half_w = w / 2.0
    half_h = h / 2.0
    local = box.new_tensor(
        [
            [-half_w, -half_h],
            [half_w, -half_h],
            [half_w, half_h],
            [-half_w, half_h],
        ]
    )
    cos_a = torch.cos(angle)
    sin_a = torch.sin(angle)
    x = cos_a * local[:, 0] - sin_a * local[:, 1] + cx
    y = sin_a * local[:, 0] + cos_a * local[:, 1] + cy
    return torch.stack([x, y], dim=1)


def _to_roi_local(corners: torch.Tensor, proposal: torch.Tensor) -> torch.Tensor:
    px, py, _, _, angle = proposal.unbind()
    dx = corners[:, 0] - px
    dy = corners[:, 1] - py
    cos_a = torch.cos(angle)
    sin_a = torch.sin(angle)
    x_local = cos_a * dx + sin_a * dy
    y_local = -sin_a * dx + cos_a * dy
    return torch.stack([x_local, y_local], dim=1)


def _convex_quad_mask(local_quad: torch.Tensor, proposal: torch.Tensor, target_size: int) -> torch.Tensor:
    width = torch.clamp(proposal[2], min=1e-6)
    height = torch.clamp(proposal[3], min=1e-6)
    xs = ((torch.arange(target_size, device=proposal.device, dtype=proposal.dtype) + 0.5) / target_size - 0.5) * width
    ys = ((torch.arange(target_size, device=proposal.device, dtype=proposal.dtype) + 0.5) / target_size - 0.5) * height
    grid_y, grid_x = torch.meshgrid(ys, xs, indexing="ij")
    points = torch.stack([grid_x, grid_y], dim=-1).reshape(-1, 2)

    v0 = local_quad
    v1 = torch.roll(local_quad, shifts=-1, dims=0)
    edges = v1 - v0
    rel = points[:, None, :] - v0[None, :, :]
    cross = edges[None, :, 0] * rel[:, :, 1] - edges[None, :, 1] * rel[:, :, 0]
    inside = torch.logical_or(torch.all(cross >= -1e-6, dim=1), torch.all(cross <= 1e-6, dim=1))
    return inside.reshape(target_size, target_size).to(dtype=proposal.dtype)


def _boundary_from_mask(mask: torch.Tensor, boundary_band_width: int) -> torch.Tensor:
    if mask.ndim != 2:
        raise ValueError("mask must be 2D")
    width = max(1, int(boundary_band_width))
    kernel = 2 * width + 1
    mask4 = mask[None, None, :, :]
    dilated = F.max_pool2d(mask4, kernel_size=kernel, stride=1, padding=width)
    eroded = 1.0 - F.max_pool2d(1.0 - mask4, kernel_size=kernel, stride=1, padding=width)
    boundary = (dilated - eroded).clamp_(0.0, 1.0)
    if float(boundary.sum()) == 0.0 and float(mask.sum()) > 0.0:
        boundary = mask4
    return boundary[0, 0]


def _oriented_rect_mask_from_local_box(
    *,
    center_x: torch.Tensor,
    center_y: torch.Tensor,
    width: torch.Tensor,
    height: torch.Tensor,
    angle: torch.Tensor,
    proposal: torch.Tensor,
    target_size: int,
) -> torch.Tensor:
    prop_width = torch.clamp(proposal[2], min=1e-6)
    prop_height = torch.clamp(proposal[3], min=1e-6)
    xs = (
        (torch.arange(target_size, device=proposal.device, dtype=proposal.dtype) + 0.5) / target_size - 0.5
    ) * prop_width
    ys = (
        (torch.arange(target_size, device=proposal.device, dtype=proposal.dtype) + 0.5) / target_size - 0.5
    ) * prop_height
    grid_y, grid_x = torch.meshgrid(ys, xs, indexing="ij")
    dx = grid_x - center_x
    dy = grid_y - center_y
    cos_a = torch.cos(angle)
    sin_a = torch.sin(angle)
    local_x = cos_a * dx + sin_a * dy
    local_y = -sin_a * dx + cos_a * dy
    inside = (local_x.abs() <= width / 2.0) & (local_y.abs() <= height / 2.0)
    return inside.to(dtype=proposal.dtype)


def _gt_box_in_proposal_local(gt_box: torch.Tensor, proposal: torch.Tensor) -> tuple[torch.Tensor, ...]:
    gt_center = gt_box[:2].unsqueeze(0)
    gt_center_local = _to_roi_local(gt_center, proposal)[0]
    rel_angle = gt_box[4] - proposal[4]
    return gt_center_local[0], gt_center_local[1], gt_box[2], gt_box[3], rel_angle


def build_boundary_aux_targets(
    *,
    sampling_results: list[object],
    target_size: int,
    boundary_band_width: int,
    device: torch.device | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    target_chunks: list[torch.Tensor] = []
    weight_chunks: list[torch.Tensor] = []

    for result in sampling_results:
        pos_bboxes = getattr(result, "pos_bboxes")
        neg_bboxes = getattr(result, "neg_bboxes")
        pos_gt_bboxes = getattr(result, "pos_gt_bboxes")
        current_device = device or pos_bboxes.device
        num_pos = int(pos_bboxes.size(0))
        num_neg = int(neg_bboxes.size(0))
        num_total = num_pos + num_neg

        sample_targets = torch.zeros((num_total, 1, target_size, target_size), device=current_device, dtype=torch.float32)
        sample_weights = torch.zeros((num_total,), device=current_device, dtype=torch.float32)

        for idx in range(num_pos):
            proposal = pos_bboxes[idx].to(device=current_device, dtype=torch.float32)
            gt_box = pos_gt_bboxes[idx].to(device=current_device, dtype=torch.float32)
            gt_corners = _obb_to_corners(gt_box)
            gt_local = _to_roi_local(gt_corners, proposal)
            mask = _convex_quad_mask(gt_local, proposal, target_size)
            boundary = _boundary_from_mask(mask, boundary_band_width)
            sample_targets[idx, 0] = boundary
            sample_weights[idx] = 1.0

        target_chunks.append(sample_targets)
        weight_chunks.append(sample_weights)

    if not target_chunks:
        empty_targets = torch.zeros((0, 1, target_size, target_size), device=device or torch.device("cpu"))
        empty_weights = torch.zeros((0,), device=device or torch.device("cpu"))
        return empty_targets, empty_weights

    return torch.cat(target_chunks, dim=0), torch.cat(weight_chunks, dim=0)


def build_topology_aux_targets(
    *,
    sampling_results: list[object],
    target_size: int,
    centerline_width: int,
    device: torch.device | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    target_chunks: list[torch.Tensor] = []
    weight_chunks: list[torch.Tensor] = []

    for result in sampling_results:
        pos_bboxes = getattr(result, "pos_bboxes")
        neg_bboxes = getattr(result, "neg_bboxes")
        pos_gt_bboxes = getattr(result, "pos_gt_bboxes")
        current_device = device or pos_bboxes.device
        num_pos = int(pos_bboxes.size(0))
        num_neg = int(neg_bboxes.size(0))
        num_total = num_pos + num_neg

        sample_targets = torch.zeros((num_total, 1, target_size, target_size), device=current_device, dtype=torch.float32)
        sample_weights = torch.zeros((num_total,), device=current_device, dtype=torch.float32)

        for idx in range(num_pos):
            proposal = pos_bboxes[idx].to(device=current_device, dtype=torch.float32)
            gt_box = pos_gt_bboxes[idx].to(device=current_device, dtype=torch.float32)
            center_x, center_y, box_w, box_h, rel_angle = _gt_box_in_proposal_local(gt_box, proposal)
            long_side = torch.maximum(box_w, box_h)
            short_side = torch.minimum(box_w, box_h)
            centerline_physical_width = torch.clamp(
                (torch.minimum(proposal[2], proposal[3]) / float(target_size)) * float(max(1, centerline_width)),
                min=short_side.new_tensor(1e-3),
                max=short_side,
            )
            topology = _oriented_rect_mask_from_local_box(
                center_x=center_x,
                center_y=center_y,
                width=long_side,
                height=centerline_physical_width,
                angle=rel_angle,
                proposal=proposal,
                target_size=target_size,
            )
            sample_targets[idx, 0] = topology
            sample_weights[idx] = 1.0

        target_chunks.append(sample_targets)
        weight_chunks.append(sample_weights)

    if not target_chunks:
        empty_targets = torch.zeros((0, 1, target_size, target_size), device=device or torch.device("cpu"))
        empty_weights = torch.zeros((0,), device=device or torch.device("cpu"))
        return empty_targets, empty_weights

    return torch.cat(target_chunks, dim=0), torch.cat(weight_chunks, dim=0)


@ROTATED_HEADS.register_module()
class OrientedBoundaryAuxBBoxHead(RotatedShared2FCBBoxHead):
    def __init__(
        self,
        *args,
        boundary_aux_loss_weight: float = 0.0,
        boundary_aux_target_size: int = 7,
        boundary_band_width: int = 1,
        topology_aux_loss_weight: float = 0.0,
        centerline_width: int = 1,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.boundary_aux_loss_weight = float(boundary_aux_loss_weight)
        self.boundary_aux_target_size = int(boundary_aux_target_size)
        self.boundary_band_width = int(boundary_band_width)
        self.topology_aux_loss_weight = float(topology_aux_loss_weight)
        self.centerline_width = int(centerline_width)
        hidden_channels = max(32, int(self.in_channels) // 2)
        self.boundary_head = nn.Sequential(
            nn.Conv2d(int(self.in_channels), hidden_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden_channels, 1, kernel_size=1),
        )
        self.centerline_head = nn.Sequential(
            nn.Conv2d(int(self.in_channels), hidden_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden_channels, 1, kernel_size=1),
        )

    def forward(
        self,
        x: torch.Tensor,
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor, torch.Tensor]:
        boundary_logits = self.boundary_head(x)
        centerline_logits = self.centerline_head(x)
        cls_score, bbox_pred = super().forward(x)
        return cls_score, bbox_pred, boundary_logits, centerline_logits

    @force_fp32(apply_to=("cls_score", "bbox_pred", "boundary_logits", "centerline_logits"))
    def loss(
        self,
        cls_score,
        bbox_pred,
        rois,
        labels,
        label_weights,
        bbox_targets,
        bbox_weights,
        boundary_logits=None,
        boundary_targets=None,
        boundary_weights=None,
        centerline_logits=None,
        centerline_targets=None,
        centerline_weights=None,
        reduction_override=None,
    ):
        losses = super().loss(
            cls_score,
            bbox_pred,
            rois,
            labels,
            label_weights,
            bbox_targets,
            bbox_weights,
            reduction_override=reduction_override,
        )
        if boundary_logits is None or boundary_targets is None or boundary_weights is None:
            losses["loss_boundary_aux"] = bbox_targets.sum() * 0
        else:
            target = boundary_targets.to(device=boundary_logits.device, dtype=boundary_logits.dtype)
            weights = boundary_weights.to(device=boundary_logits.device, dtype=boundary_logits.dtype).view(-1, 1, 1, 1)
            if target.shape[-2:] != boundary_logits.shape[-2:]:
                target = F.interpolate(target, size=boundary_logits.shape[-2:], mode="nearest")
            if float(weights.sum()) <= 0.0 or self.boundary_aux_loss_weight <= 0.0:
                losses["loss_boundary_aux"] = boundary_logits.sum() * 0
            else:
                loss_map = F.binary_cross_entropy_with_logits(boundary_logits, target, reduction="none")
                denom = weights.sum() * float(boundary_logits.shape[-1] * boundary_logits.shape[-2])
                losses["loss_boundary_aux"] = (loss_map * weights).sum() / denom.clamp(min=1.0)
                losses["loss_boundary_aux"] = losses["loss_boundary_aux"] * self.boundary_aux_loss_weight

        if centerline_logits is None or centerline_targets is None or centerline_weights is None:
            losses["loss_topology_aux"] = bbox_targets.sum() * 0
            return losses

        target = centerline_targets.to(device=centerline_logits.device, dtype=centerline_logits.dtype)
        weights = centerline_weights.to(device=centerline_logits.device, dtype=centerline_logits.dtype).view(-1, 1, 1, 1)
        if target.shape[-2:] != centerline_logits.shape[-2:]:
            target = F.interpolate(target, size=centerline_logits.shape[-2:], mode="nearest")
        if float(weights.sum()) <= 0.0 or self.topology_aux_loss_weight <= 0.0:
            losses["loss_topology_aux"] = centerline_logits.sum() * 0
            return losses

        loss_map = F.binary_cross_entropy_with_logits(centerline_logits, target, reduction="none")
        denom = weights.sum() * float(centerline_logits.shape[-1] * centerline_logits.shape[-2])
        bce_loss = (loss_map * weights).sum() / denom.clamp(min=1.0)

        pred_prob = torch.sigmoid(centerline_logits)
        intersection = (pred_prob * target * weights).sum()
        recall = intersection / (target.mul(weights).sum().clamp(min=1.0))
        topology_recall_loss = 1.0 - recall
        losses["loss_topology_aux"] = (bce_loss + topology_recall_loss) * self.topology_aux_loss_weight
        return losses


@ROTATED_HEADS.register_module()
class OrientedBoundaryAuxRoIHead(OrientedStandardRoIHead):
    def _bbox_forward(self, x, rois):
        bbox_feats = self.bbox_roi_extractor(x[: self.bbox_roi_extractor.num_inputs], rois)
        if self.with_shared_head:
            bbox_feats = self.shared_head(bbox_feats)
        cls_score, bbox_pred, boundary_logits, centerline_logits = self.bbox_head(bbox_feats)
        return dict(
            cls_score=cls_score,
            bbox_pred=bbox_pred,
            boundary_logits=boundary_logits,
            centerline_logits=centerline_logits,
            bbox_feats=bbox_feats,
        )

    def _bbox_forward_train(self, x, sampling_results, gt_bboxes, gt_labels, img_metas):
        del img_metas
        rois = rbbox2roi([res.bboxes for res in sampling_results])
        bbox_results = self._bbox_forward(x, rois)
        bbox_targets = self.bbox_head.get_targets(sampling_results, gt_bboxes, gt_labels, self.train_cfg)
        boundary_targets, boundary_weights = build_boundary_aux_targets(
            sampling_results=sampling_results,
            target_size=int(getattr(self.bbox_head, "boundary_aux_target_size", 7)),
            boundary_band_width=int(getattr(self.bbox_head, "boundary_band_width", 1)),
            device=rois.device,
        )
        centerline_targets, centerline_weights = build_topology_aux_targets(
            sampling_results=sampling_results,
            target_size=int(getattr(self.bbox_head, "boundary_aux_target_size", 7)),
            centerline_width=int(getattr(self.bbox_head, "centerline_width", 1)),
            device=rois.device,
        )
        loss_bbox = self.bbox_head.loss(
            bbox_results["cls_score"],
            bbox_results["bbox_pred"],
            rois,
            *bbox_targets,
            boundary_logits=bbox_results["boundary_logits"],
            boundary_targets=boundary_targets,
            boundary_weights=boundary_weights,
            centerline_logits=bbox_results["centerline_logits"],
            centerline_targets=centerline_targets,
            centerline_weights=centerline_weights,
        )
        bbox_results.update(loss_bbox=loss_bbox)
        return bbox_results
