from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx

from saki_plugin_sdk import (
    filter_options,
    PluginConfig,
    PluginManifest,
    WorkspaceProtocol,
)
from saki_plugin_sdk.augmentations import build_default_augmentation_specs
from saki_plugin_sdk.strategies.builtin import CANONICAL_AUG_IOU_STRATEGY, normalize_strategy_name


class YoloConfigService:
    _VALID_YOLO_TASKS = ("detect", "obb")
    _DEFAULT_AUG_NAMES = tuple(spec.name for spec in build_default_augmentation_specs())

    def __init__(self) -> None:
        self._manifest = PluginManifest.from_yaml(
            Path(__file__).resolve().parents[2] / "plugin.yml"
        )
        self._task_presets = self._extract_task_presets_from_manifest()

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def _extract_task_presets_from_manifest(self) -> dict[str, tuple[str, ...]]:
        schema = self._manifest.config_schema if isinstance(self._manifest.config_schema, dict) else {}
        fields = schema.get("fields")
        if not isinstance(fields, list):
            raise ValueError("plugin manifest config_schema.fields must be a list")
        model_preset_field = next(
            (
                item
                for item in fields
                if isinstance(item, dict) and str(item.get("key") or "").strip() == "model_preset"
            ),
            None,
        )
        if not isinstance(model_preset_field, dict):
            raise ValueError("plugin manifest config_schema.fields missing model_preset field")
        options_raw = model_preset_field.get("options")
        options = options_raw if isinstance(options_raw, list) else []

        task_presets: dict[str, tuple[str, ...]] = {}
        for task in self._VALID_YOLO_TASKS:
            filtered = filter_options(
                [item for item in options if isinstance(item, dict)],
                context={
                    "fieldValues": {"yolo_task": task},
                },
            )
            ordered_values: list[str] = []
            seen: set[str] = set()
            for option in filtered:
                value = str(option.get("value") or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                ordered_values.append(value)
            if not ordered_values:
                raise ValueError(
                    f"manifest model_preset options must include at least one preset for yolo_task={task}"
                )
            task_presets[task] = tuple(ordered_values)
        return task_presets

    @staticmethod
    def _read_param(payload: Any, key: str, default: Any = None) -> Any:
        if isinstance(payload, dict):
            return payload.get(key, default)
        return getattr(payload, key, default)

    def _presets_for_task(self, yolo_task: str) -> tuple[str, ...]:
        task = str(yolo_task or "").strip().lower()
        presets = self._task_presets.get(task)
        if not presets:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        return presets

    def resolve_config(
        self,
        raw_config: dict[str, Any] | None,
        *,
        strategy: str | None = None,
    ) -> PluginConfig:
        config = PluginConfig.from_manifest(
            self._manifest,
            raw_config if isinstance(raw_config, dict) else None,
            validate=True,
        )
        return self._validate_and_normalize_config(config, strategy=strategy)

    @classmethod
    def _normalize_aug_names(cls, values: list[Any]) -> tuple[str, ...]:
        allowed = set(cls._DEFAULT_AUG_NAMES)
        requested: set[str] = set()
        for raw in values:
            name = str(raw or "").strip().lower()
            if not name:
                continue
            if name not in allowed:
                raise ValueError(
                    f"aug_iou_enabled_augs has unsupported op={name!r}; allowed={list(cls._DEFAULT_AUG_NAMES)}"
                )
            requested.add(name)
        return tuple(name for name in cls._DEFAULT_AUG_NAMES if name in requested)

    def _validate_and_normalize_config(
        self,
        config: PluginConfig,
        *,
        strategy: str | None = None,
    ) -> PluginConfig:
        yolo_task = str(config.yolo_task).strip().lower()
        if yolo_task not in self._VALID_YOLO_TASKS:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        allowed_presets = self._presets_for_task(yolo_task)

        source = str(config.model_source).strip().lower()
        preset_val = self._read_param(config, "model_preset")
        preset = str(preset_val or "").strip()
        if source == "preset":
            if not preset:
                preset = allowed_presets[0]
            if preset not in allowed_presets:
                raise ValueError(
                    f"model_preset={preset or '<empty>'} is not allowed for yolo_task={yolo_task}; "
                    f"allowed={list(allowed_presets)}"
                )

        custom_ref_val = self._read_param(config, "model_custom_ref")
        custom_ref = str(custom_ref_val or "").strip()
        if source != "preset" and not custom_ref:
            raise ValueError("model_custom_ref is required for custom model source")

        strategy_key = normalize_strategy_name(strategy or "")
        aug_raw = self._read_param(config, "aug_iou_enabled_augs")
        if aug_raw is None:
            aug_values: list[Any] = []
        elif isinstance(aug_raw, (list, tuple, set)):
            aug_values = list(aug_raw)
        else:
            raise ValueError("aug_iou_enabled_augs must be an array")
        aug_enabled = self._normalize_aug_names(aug_values)
        if strategy_key == CANONICAL_AUG_IOU_STRATEGY:
            if not aug_enabled:
                raise ValueError("strategy=aug_iou_disagreement requires non-empty aug_iou_enabled_augs")
            if "identity" not in set(aug_enabled):
                raise ValueError("aug_iou_enabled_augs must include 'identity' for aug_iou_disagreement")

        return config.model_copy(
            update={
                "yolo_task": yolo_task,
                "model_source": source,
                "model_preset": preset,
                "model_custom_ref": "" if source == "preset" else custom_ref,
                "aug_iou_enabled_augs": list(aug_enabled),
            }
        )

    def validate_params(self, params: dict[str, Any], *, strategy: str | None = None) -> None:
        self.resolve_config(params, strategy=strategy)

    async def resolve_model_ref(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: Any,
    ) -> str:
        source = str(self._read_param(params, "model_source", "preset") or "preset").strip().lower()
        yolo_task = str(self._read_param(params, "yolo_task", "obb") or "obb").strip().lower()
        allowed_presets = self._presets_for_task(yolo_task)

        if source == "preset":
            preset = str(self._read_param(params, "model_preset") or "").strip()
            if not preset:
                preset = allowed_presets[0]
            if preset not in allowed_presets:
                raise RuntimeError(
                    f"model_preset={preset} is not allowed for yolo_task={yolo_task}; "
                    f"allowed={list(allowed_presets)}"
                )
            return preset

        custom_ref = str(self._read_param(params, "model_custom_ref") or "").strip()
        if not custom_ref:
            raise RuntimeError("model_custom_ref is required")

        if source == "custom_local":
            local_path = Path(custom_ref).expanduser()
            if not local_path.exists():
                raise RuntimeError(f"custom local model not found: {local_path}")
            return str(local_path)

        if source == "custom_url":
            cache_key = hashlib.sha256(custom_ref.encode("utf-8")).hexdigest()
            target = workspace.cache_dir / "model_refs" / f"{cache_key}.pt"
            if not target.exists():
                await self._download_to_file(custom_ref, target)
            return str(target)

        raise RuntimeError(f"unsupported model_source: {source or '<empty>'}")

    async def resolve_best_or_fallback_model(self, *, workspace: WorkspaceProtocol, params: Any) -> str:
        best_path = workspace.artifacts_dir / "best.pt"
        if best_path.exists():
            return str(best_path)
        return await self.resolve_model_ref(workspace=workspace, params=params)

    async def _download_to_file(self, url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
