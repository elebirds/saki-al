from __future__ import annotations

"""Oriented R-CNN 插件配置服务。

设计要点：
1. 统一从 plugin.yml schema 解析，避免前后端配置语义漂移。
2. 在这里做强约束校验（模型来源、阈值区间、枚举值），
   让 train/predict 代码只处理业务，不再分散做防御判断。
"""

import hashlib
from pathlib import Path
from typing import Any

import httpx

from saki_plugin_sdk import PluginConfig, PluginManifest, WorkspaceProtocol

from saki_plugin_oriented_rcnn.common import to_float, to_int
from saki_plugin_oriented_rcnn.types import OrientedRCNNConfig


class OrientedRCNNConfigService:
    _VALID_MODEL_SOURCES = ("preset", "custom_local", "custom_url")
    _VALID_GEOMETRY_MODES = ("auto", "obb", "rect")

    def __init__(self) -> None:
        self._manifest = PluginManifest.from_yaml(
            Path(__file__).resolve().parents[2] / "plugin.yml"
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def resolve_config(self, raw_config: dict[str, Any] | None) -> OrientedRCNNConfig:
        config = PluginConfig.from_manifest(
            self._manifest,
            raw_config if isinstance(raw_config, dict) else None,
            validate=True,
        )

        model_source = str(getattr(config, "model_source", "preset") or "preset").strip().lower()
        if model_source not in self._VALID_MODEL_SOURCES:
            raise ValueError(f"unsupported model_source: {model_source!r}")

        model_preset = str(getattr(config, "model_preset", "") or "").strip()
        if model_source == "preset" and not model_preset:
            raise ValueError("model_preset is required when model_source=preset")

        model_custom_ref = str(getattr(config, "model_custom_ref", "") or "").strip()
        if model_source in {"custom_local", "custom_url"} and not model_custom_ref:
            raise ValueError("model_custom_ref is required for custom model source")

        geometry_mode = str(getattr(config, "predict_geometry_mode", "auto") or "auto").strip().lower()
        if geometry_mode not in self._VALID_GEOMETRY_MODES:
            raise ValueError(f"unsupported predict_geometry_mode: {geometry_mode!r}")

        annotation_types_raw = getattr(config, "annotation_types", [])
        annotation_types = tuple(
            sorted(
                {
                    str(item).strip().lower()
                    for item in (annotation_types_raw if isinstance(annotation_types_raw, (list, tuple, set)) else [])
                    if str(item).strip()
                }
            )
        )

        return OrientedRCNNConfig(
            epochs=max(1, to_int(getattr(config, "epochs", 12), 12)),
            batch=max(1, to_int(getattr(config, "batch", 2), 2)),
            imgsz=max(256, to_int(getattr(config, "imgsz", 1024), 1024)),
            workers=max(0, to_int(getattr(config, "workers", 2), 2)),
            predict_conf=min(1.0, max(0.0, to_float(getattr(config, "predict_conf", 0.05), 0.05))),
            val_split_ratio=min(0.5, max(0.05, to_float(getattr(config, "val_split_ratio", 0.2), 0.2))),
            model_source=model_source,
            model_preset=model_preset,
            model_custom_ref=model_custom_ref,
            nms_iou_thr=min(0.95, max(0.01, to_float(getattr(config, "nms_iou_thr", 0.1), 0.1))),
            max_per_img=max(10, to_int(getattr(config, "max_per_img", 2000), 2000)),
            predict_geometry_mode=geometry_mode,
            device=str(getattr(config, "device", "auto") or "auto").strip().lower(),
            annotation_types=annotation_types,
            split_seed=max(0, to_int(getattr(config, "split_seed", 0), 0)),
            train_seed=max(0, to_int(getattr(config, "train_seed", 0), 0)),
            sampling_seed=max(0, to_int(getattr(config, "sampling_seed", 0), 0)),
            round_index=max(1, to_int(getattr(config, "round_index", 1), 1)),
        )

    def validate_params(self, params: dict[str, Any]) -> None:
        _ = self.resolve_config(params)

    async def resolve_model_ref(
        self,
        *,
        workspace: WorkspaceProtocol,
        config: OrientedRCNNConfig,
    ) -> str:
        """解析模型来源。

        - preset: 返回预设配置 ID（后续由训练/推理服务映射到真实 cfg + ckpt）
        - custom_local: 校验本地路径存在
        - custom_url: 下载到 workspace cache 后返回本地路径
        """
        if config.model_source == "preset":
            return config.model_preset

        if config.model_source == "custom_local":
            path = Path(config.model_custom_ref).expanduser()
            if not path.exists():
                raise RuntimeError(f"custom local model not found: {path}")
            return str(path)

        if config.model_source == "custom_url":
            cache_key = hashlib.sha256(config.model_custom_ref.encode("utf-8")).hexdigest()
            target = workspace.cache_dir / "model_refs" / f"{cache_key}.pth"
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                await self._download_to_file(config.model_custom_ref, target)
            return str(target)

        raise RuntimeError(f"unsupported model_source: {config.model_source}")

    async def resolve_best_or_fallback_model(
        self,
        *,
        workspace: WorkspaceProtocol,
        config: OrientedRCNNConfig,
    ) -> str:
        best_path = workspace.artifacts_dir / "best.pth"
        if best_path.exists():
            return str(best_path)
        return await self.resolve_model_ref(workspace=workspace, config=config)

    async def _download_to_file(self, url: str, target: Path) -> None:
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
