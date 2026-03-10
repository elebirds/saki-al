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
    _VALID_MODEL_SOURCES = ("preset", "custom_local", "custom_url")
    _VALID_INIT_MODES = ("checkpoint_direct", "arch_yaml_plus_weights")
    _VALID_MODEL_ARCH_SOURCES = ("builtin", "custom_local")
    _VALID_TRAIN_BUDGET_MODES = ("fixed_epochs", "target_updates")
    _DEFAULT_AUG_NAMES = tuple(spec.name for spec in build_default_augmentation_specs())
    _VALID_AUG_IOU_MODES = ("rect", "obb", "boundary")
    _WORKERS_MIN = 0
    _WORKERS_MAX = 32
    _WORKERS_DEFAULT = 2
    _MIN_EPOCHS_DEFAULT = 1
    _MAX_EPOCHS_DEFAULT = 1000

    def __init__(self) -> None:
        self._manifest = PluginManifest.from_yaml(
            Path(__file__).resolve().parents[2] / "plugin.yml"
        )
        self._task_presets = self._extract_task_presets_from_manifest()
        self._task_arch_presets = self._extract_task_arch_presets_from_manifest()

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def _extract_task_option_values_from_manifest(
        self,
        *,
        field_key: str,
        field_label: str,
    ) -> dict[str, tuple[str, ...]]:
        schema = self._manifest.config_schema if isinstance(self._manifest.config_schema, dict) else {}
        fields = schema.get("fields")
        if not isinstance(fields, list):
            raise ValueError("plugin manifest config_schema.fields must be a list")
        target_field = next(
            (
                item
                for item in fields
                if isinstance(item, dict) and str(item.get("key") or "").strip() == field_key
            ),
            None,
        )
        if not isinstance(target_field, dict):
            raise ValueError(f"plugin manifest config_schema.fields missing {field_key} field")
        options_raw = target_field.get("options")
        options = options_raw if isinstance(options_raw, list) else []

        task_values: dict[str, tuple[str, ...]] = {}
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
                value = str(option.get("value") or "").strip().lower()
                if not value or value in seen:
                    continue
                seen.add(value)
                ordered_values.append(value)
            if not ordered_values:
                raise ValueError(
                    f"manifest {field_label} options must include at least one preset for yolo_task={task}"
                )
            task_values[task] = tuple(ordered_values)
        return task_values

    def _extract_task_presets_from_manifest(self) -> dict[str, tuple[str, ...]]:
        return self._extract_task_option_values_from_manifest(
            field_key="model_preset",
            field_label="model_preset",
        )

    def _extract_task_arch_presets_from_manifest(self) -> dict[str, tuple[str, ...]]:
        return self._extract_task_option_values_from_manifest(
            field_key="model_arch_preset",
            field_label="model_arch_preset",
        )

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

    def _arch_presets_for_task(self, yolo_task: str) -> tuple[str, ...]:
        task = str(yolo_task or "").strip().lower()
        presets = self._task_arch_presets.get(task)
        if not presets:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        return presets

    @staticmethod
    def _basename_from_ref(model_ref: str) -> str:
        raw = str(model_ref or "").strip()
        if not raw:
            return ""
        return Path(raw.split("?", 1)[0]).name.strip().lower()

    def _infer_arch_preset(
        self,
        *,
        yolo_task: str,
        model_source: str,
        model_preset: str,
        model_custom_ref: str,
    ) -> str:
        allowed = set(self._arch_presets_for_task(yolo_task))
        if model_source == "preset":
            basename = self._basename_from_ref(model_preset)
        else:
            basename = self._basename_from_ref(model_custom_ref)
        if not basename:
            return ""
        if basename in allowed:
            return basename
        if basename.endswith(".pt"):
            candidate = f"{basename[:-3]}.yaml"
            if candidate in allowed:
                return candidate
        return ""

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
        if source not in self._VALID_MODEL_SOURCES:
            raise ValueError(f"unsupported model_source: {source!r}, must be one of {self._VALID_MODEL_SOURCES}")
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

        init_mode = str(self._read_param(config, "init_mode", "checkpoint_direct") or "checkpoint_direct").strip().lower()
        if init_mode not in self._VALID_INIT_MODES:
            raise ValueError(f"unsupported init_mode: {init_mode!r}, must be one of {self._VALID_INIT_MODES}")
        arch_source = str(self._read_param(config, "model_arch_source", "builtin") or "builtin").strip().lower()
        arch_preset = str(self._read_param(config, "model_arch_preset") or "").strip().lower()
        arch_custom_ref = str(self._read_param(config, "model_arch_custom_ref") or "").strip()
        if init_mode == "arch_yaml_plus_weights":
            if arch_source not in self._VALID_MODEL_ARCH_SOURCES:
                raise ValueError(
                    f"unsupported model_arch_source: {arch_source!r}, must be one of {self._VALID_MODEL_ARCH_SOURCES}"
                )
            if arch_source == "builtin":
                allowed_arch_presets = self._arch_presets_for_task(yolo_task)
                if not arch_preset:
                    arch_preset = self._infer_arch_preset(
                        yolo_task=yolo_task,
                        model_source=source,
                        model_preset=preset,
                        model_custom_ref=custom_ref,
                    )
                if not arch_preset:
                    raise ValueError(
                        "model_arch_preset is required for init_mode=arch_yaml_plus_weights "
                        "when model_arch_source=builtin and cannot infer from model reference"
                    )
                if arch_preset not in allowed_arch_presets:
                    raise ValueError(
                        f"model_arch_preset={arch_preset or '<empty>'} is not allowed for yolo_task={yolo_task}; "
                        f"allowed={list(allowed_arch_presets)}"
                    )
                arch_custom_ref = ""
            else:
                if not arch_custom_ref:
                    raise ValueError(
                        "model_arch_custom_ref is required for init_mode=arch_yaml_plus_weights "
                        "when model_arch_source=custom_local"
                    )
                arch_preset = ""
        else:
            arch_source = "builtin"
            arch_preset = ""
            arch_custom_ref = ""

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
        aug_iou_mode = str(self._read_param(config, "aug_iou_iou_mode", "obb") or "obb").strip().lower()
        if aug_iou_mode not in self._VALID_AUG_IOU_MODES:
            raise ValueError(
                f"unsupported aug_iou_iou_mode: {aug_iou_mode!r}, must be one of {self._VALID_AUG_IOU_MODES}"
            )
        try:
            aug_iou_boundary_d = int(self._read_param(config, "aug_iou_boundary_d", 3))
        except Exception:
            aug_iou_boundary_d = 3
        aug_iou_boundary_d = max(1, min(128, aug_iou_boundary_d))
        try:
            workers = int(self._read_param(config, "workers", self._WORKERS_DEFAULT))
        except Exception:
            workers = self._WORKERS_DEFAULT
        workers = max(self._WORKERS_MIN, min(self._WORKERS_MAX, workers))
        train_budget_mode = str(
            self._read_param(config, "train_budget_mode", "fixed_epochs") or "fixed_epochs"
        ).strip().lower()
        if train_budget_mode not in self._VALID_TRAIN_BUDGET_MODES:
            raise ValueError(
                "unsupported train_budget_mode: "
                f"{train_budget_mode!r}, must be one of {self._VALID_TRAIN_BUDGET_MODES}"
            )
        try:
            min_epochs = int(self._read_param(config, "min_epochs", self._MIN_EPOCHS_DEFAULT))
        except Exception:
            min_epochs = self._MIN_EPOCHS_DEFAULT
        try:
            max_epochs = int(self._read_param(config, "max_epochs", self._MAX_EPOCHS_DEFAULT))
        except Exception:
            max_epochs = self._MAX_EPOCHS_DEFAULT
        if min_epochs < 1:
            raise ValueError("min_epochs must be >= 1")
        if max_epochs < 1:
            raise ValueError("max_epochs must be >= 1")
        if min_epochs > max_epochs:
            raise ValueError("min_epochs must be <= max_epochs")
        raw_target_updates = self._read_param(config, "target_updates", None)
        if raw_target_updates in (None, ""):
            target_updates = 0
        else:
            try:
                target_updates = int(raw_target_updates)
            except Exception as exc:
                raise ValueError("target_updates must be an integer") from exc
        if train_budget_mode == "target_updates" and target_updates <= 0:
            raise ValueError("target_updates must be > 0 when train_budget_mode=target_updates")
        raw_disable_early_stop = self._read_param(config, "budget_disable_early_stop", True)
        if isinstance(raw_disable_early_stop, str):
            budget_disable_early_stop = raw_disable_early_stop.strip().lower() not in {
                "",
                "0",
                "false",
                "no",
                "off",
            }
        else:
            budget_disable_early_stop = bool(raw_disable_early_stop)

        return config.model_copy(
            update={
                "yolo_task": yolo_task,
                "model_source": source,
                "model_preset": preset,
                "model_custom_ref": "" if source == "preset" else custom_ref,
                "init_mode": init_mode,
                "model_arch_source": arch_source,
                "model_arch_preset": arch_preset,
                "model_arch_custom_ref": arch_custom_ref,
                "aug_iou_enabled_augs": list(aug_enabled),
                "aug_iou_iou_mode": aug_iou_mode,
                "aug_iou_boundary_d": aug_iou_boundary_d,
                "workers": workers,
                "train_budget_mode": train_budget_mode,
                "target_updates": target_updates,
                "min_epochs": min_epochs,
                "max_epochs": max_epochs,
                "budget_disable_early_stop": budget_disable_early_stop,
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

    async def resolve_arch_yaml_ref(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: Any,
    ) -> str:
        del workspace
        init_mode = str(self._read_param(params, "init_mode", "checkpoint_direct") or "checkpoint_direct").strip().lower()
        if init_mode != "arch_yaml_plus_weights":
            return ""
        yolo_task = str(self._read_param(params, "yolo_task", "obb") or "obb").strip().lower()
        arch_source = str(self._read_param(params, "model_arch_source", "builtin") or "builtin").strip().lower()
        arch_preset = str(self._read_param(params, "model_arch_preset") or "").strip().lower()
        arch_custom_ref = str(self._read_param(params, "model_arch_custom_ref") or "").strip()

        if arch_source == "builtin":
            if not arch_preset:
                model_source = str(self._read_param(params, "model_source", "preset") or "preset").strip().lower()
                model_preset = str(self._read_param(params, "model_preset") or "").strip()
                model_custom_ref = str(self._read_param(params, "model_custom_ref") or "").strip()
                arch_preset = self._infer_arch_preset(
                    yolo_task=yolo_task,
                    model_source=model_source,
                    model_preset=model_preset,
                    model_custom_ref=model_custom_ref,
                )
            allowed_arch_presets = self._arch_presets_for_task(yolo_task)
            if not arch_preset:
                raise RuntimeError(
                    "model_arch_preset is required for init_mode=arch_yaml_plus_weights "
                    "when model_arch_source=builtin and cannot infer from model reference"
                )
            if arch_preset not in allowed_arch_presets:
                raise RuntimeError(
                    f"model_arch_preset={arch_preset} is not allowed for yolo_task={yolo_task}; "
                    f"allowed={list(allowed_arch_presets)}"
                )
            return arch_preset

        if arch_source == "custom_local":
            if not arch_custom_ref:
                raise RuntimeError("model_arch_custom_ref is required")
            arch_path = Path(arch_custom_ref).expanduser()
            if not arch_path.exists():
                raise RuntimeError(f"custom local model yaml not found: {arch_path}")
            if arch_path.suffix.lower() not in (".yaml", ".yml"):
                raise RuntimeError("model_arch_custom_ref must be a .yaml or .yml file")
            return str(arch_path)

        raise RuntimeError(
            f"unsupported model_arch_source: {arch_source or '<empty>'}, "
            f"must be one of {self._VALID_MODEL_ARCH_SOURCES}"
        )

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
