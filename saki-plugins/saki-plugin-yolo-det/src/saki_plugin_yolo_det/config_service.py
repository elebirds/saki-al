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
    available_accelerators,
    normalize_accelerator_name,
    probe_hardware,
)


class YoloConfigService:
    _VALID_YOLO_TASKS = ("detect", "obb")

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

    def _presets_for_task(self, yolo_task: str) -> tuple[str, ...]:
        task = str(yolo_task or "").strip().lower()
        presets = self._task_presets.get(task)
        if not presets:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        return presets

    def resolve_config(self, raw_config: dict[str, Any] | None) -> PluginConfig:
        config = PluginConfig.from_manifest(
            self._manifest,
            raw_config if isinstance(raw_config, dict) else None,
            validate=True,
        )
        return self._validate_and_normalize_config(config)

    def _validate_and_normalize_config(self, config: PluginConfig) -> PluginConfig:
        yolo_task = str(config.yolo_task).strip().lower()
        if yolo_task not in self._VALID_YOLO_TASKS:
            raise ValueError(f"unsupported yolo_task: {yolo_task!r}, must be one of {self._VALID_YOLO_TASKS}")
        allowed_presets = self._presets_for_task(yolo_task)

        source = str(config.model_source).strip().lower()
        preset_val = config.get("model_preset", None)
        preset = str(preset_val or "").strip()
        if source == "preset":
            if not preset:
                preset = allowed_presets[0]
            if preset not in allowed_presets:
                raise ValueError(
                    f"model_preset={preset or '<empty>'} is not allowed for yolo_task={yolo_task}; "
                    f"allowed={list(allowed_presets)}"
                )

        custom_ref_val = config.get("model_custom_ref", None)
        custom_ref = str(custom_ref_val or "").strip()
        if source != "preset" and not custom_ref:
            raise ValueError("model_custom_ref is required for custom model source")

        return config.model_copy(
            update={
                "yolo_task": yolo_task,
                "model_source": source,
                "model_preset": preset,
                "model_custom_ref": "" if source == "preset" else custom_ref,
            }
        )

    def validate_params(self, params: dict[str, Any]) -> None:
        self.resolve_config(params)

    def resolve_device(
        self,
        params: Any,
        *,
        supported_accelerators: list[str],
        preferred_backend: str = "",
    ) -> tuple[Any, str, str]:
        requested_raw = params.get("device", "auto")
        requested = normalize_accelerator_name(requested_raw) or "auto"
        preferred = normalize_accelerator_name(preferred_backend or params.get("_resolved_device_backend"))

        available = available_accelerators(
            probe_hardware(
                cpu_workers=1,
                memory_mb=0,
            )
        )
        supported = {
            normalize_accelerator_name(item)
            for item in supported_accelerators
            if normalize_accelerator_name(item) and normalize_accelerator_name(item) != "auto"
        }
        supported = supported or {"cpu"}
        candidates = available & supported

        if requested != "auto":
            if requested == "cuda" and requested not in candidates:
                raise ValueError(
                    f"Invalid CUDA 'device={requested_raw}' requested. Use 'device=cpu' if no CUDA device is available."
                )
            if requested not in candidates:
                raise ValueError(
                    f"Requested device '{requested_raw}' is not available on this executor. "
                    f"available={sorted(available)} supported={sorted(supported)}"
                )
            if requested == "cuda":
                raw = str(requested_raw).strip()
                if raw and (raw.isdigit() or raw.startswith("cuda:") or "," in raw):
                    return requested_raw, str(requested_raw), requested
                return "0", str(requested_raw), requested
            if requested == "mps":
                return "mps", str(requested_raw), requested
            return "cpu", str(requested_raw), requested

        order = ["cuda", "cpu", "mps"]
        if preferred in order and preferred != "mps":
            order = [preferred] + [item for item in order if item != preferred]
        resolved_backend = next((item for item in order if item in candidates), "")
        if not resolved_backend:
            raise ValueError(
                f"No available accelerator for auto mode. available={sorted(available)} supported={sorted(supported)}"
            )
        if resolved_backend == "cuda":
            return "0", str(requested_raw), resolved_backend
        if resolved_backend == "mps":
            return "mps", str(requested_raw), resolved_backend
        return "cpu", str(requested_raw), resolved_backend

    async def resolve_model_ref(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: Any,
    ) -> str:
        source = str(params.get("model_source") or "preset").strip().lower()
        yolo_task = str(params.get("yolo_task") or "obb").strip().lower()
        allowed_presets = self._presets_for_task(yolo_task)

        if source == "preset":
            preset = str(params.get("model_preset") or "").strip()
            if not preset:
                preset = allowed_presets[0]
            if preset not in allowed_presets:
                raise RuntimeError(
                    f"model_preset={preset} is not allowed for yolo_task={yolo_task}; "
                    f"allowed={list(allowed_presets)}"
                )
            return preset

        custom_ref = str(params.get("model_custom_ref") or "").strip()
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
