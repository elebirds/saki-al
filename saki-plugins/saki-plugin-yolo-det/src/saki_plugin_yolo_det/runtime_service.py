from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Callable
import warnings

from saki_plugin_sdk import (
    EventCallback,
    ExecutionBindingContext,
    RuntimeCapabilitySnapshot,
    TrainArtifact,
    TrainOutput,
    WorkspaceProtocol,
)
from saki_plugin_sdk.manifest import PluginManifest
from saki_plugin_yolo_det.common import infer_image_hw, to_bool, to_float, to_int
from saki_plugin_yolo_det.config_service import YoloConfigService
from saki_plugin_yolo_det.eval_service import YoloEvalService
from saki_plugin_yolo_det.metrics_parser import (
    normalize_metrics as normalize_metrics_row,
    parse_results_csv as parse_results_csv_rows,
)
from saki_plugin_yolo_det.predict_service import YoloPredictService
from saki_plugin_yolo_det.prepare_pipeline import prepare_yolo_dataset
from saki_plugin_yolo_det.train_async import (
    load_prepare_stats,
    normalize_training_metrics,
    resolve_train_config,
    run_train_with_epoch_stream,
)
from saki_plugin_yolo_det.train_sync_runner import run_train_sync
from saki_plugin_yolo_det.runtime_probe_torch import probe_torch_runtime_capability


class YoloRuntimeService:
    _CJK_FONT_CANDIDATES = (
        "PingFang SC",
        "Hiragino Sans GB",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Zen Hei",
        "Microsoft YaHei",
        "SimHei",
    )

    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._font_setup_lock = threading.Lock()
        self._font_setup_done = False
        self._config_service = YoloConfigService()
        self._eval_service = YoloEvalService(
            config_service=self._config_service,
            load_yolo=self._load_yolo,
            normalize_metrics=self._normalize_metrics,
        )
        self._predict_service = YoloPredictService(
            stop_flag=self._stop_flag,
            config_service=self._config_service,
            load_yolo=self._load_yolo,
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._config_service.manifest

    def validate_params(self, params: dict[str, Any]) -> None:
        self._config_service.validate_params(params)

    def probe_runtime_capability(self) -> RuntimeCapabilitySnapshot:
        return probe_torch_runtime_capability()

    @staticmethod
    def _infer_yolo_task_from_ir(dataset_ir: Any) -> str:
        if dataset_ir is None:
            return "detect"
        try:
            for item in getattr(dataset_ir, "items", []):
                annotation = getattr(item, "annotation", None)
                geometry = getattr(annotation, "geometry", None)
                if geometry is None:
                    continue
                if getattr(geometry, "obb", None) and geometry.obb.ListFields():
                    return "obb"
        except Exception:
            return "detect"
        return "detect"

    async def prepare_data(
        self,
        *,
        workspace: WorkspaceProtocol,
        labels: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
        dataset_ir: Any,
        splits: dict[str, list[dict[str, Any]]] | None = None,
        context: ExecutionBindingContext,
    ) -> None:
        del annotations, context
        yolo_task = self._infer_yolo_task_from_ir(dataset_ir)

        prepare_yolo_dataset(
            workspace=workspace,
            labels=labels,
            samples=samples,
            infer_image_hw=infer_image_hw,
            to_int=to_int,
            dataset_ir=dataset_ir,
            splits=splits,
            yolo_task=yolo_task,
        )

    async def train(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._stop_flag.clear()
        raw_params = dict(params or {})
        step_context = context.step_context
        raw_params.setdefault("split_seed", step_context.split_seed)
        raw_params.setdefault("train_seed", step_context.train_seed)
        raw_params.setdefault("sampling_seed", step_context.sampling_seed)
        raw_params.setdefault("round_index", step_context.round_index)
        raw_params.setdefault("_resolved_device_backend", context.device_binding.backend)

        resolved_params = self._config_service.resolve_config(raw_params)
        config = await resolve_train_config(
            workspace=workspace,
            plugin_config=resolved_params,
            execution_context=context,
            resolve_model_ref=self._config_service.resolve_model_ref,
        )
        await emit(
            "log",
            {
                "level": "INFO",
                "message": (
                    f"training reproducibility train_seed={config.train_seed} "
                    f"deterministic={config.deterministic} "
                    f"split_seed={getattr(resolved_params, 'split_seed', 0)}"
                ),
            },
        )
        train_result = await run_train_with_epoch_stream(
            workspace=workspace,
            config=config,
            emit=emit,
            run_train_sync=self._run_train_sync,
            to_int=to_int,
        )
        prepare_stats = load_prepare_stats(workspace)
        metrics = normalize_training_metrics(
            metrics=dict(train_result["metrics"]),
            prepare_stats=prepare_stats,
            to_int=to_int,
            to_bool=to_bool,
        )
        report_path = self._write_training_report(
            workspace=workspace,
            metrics=metrics,
            train_result=train_result,
            prepare_stats=prepare_stats,
        )
        return self._build_train_output(
            metrics=metrics,
            train_result=train_result,
            report_path=report_path,
        )

    async def eval(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._stop_flag.clear()
        return await self._eval_service.eval(
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def predict_unlabeled(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        return await self._predict_service.predict_unlabeled(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def predict_unlabeled_batch(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        self._stop_flag.clear()
        return await self._predict_service.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def stop(self, step_id: str) -> None:
        del step_id
        self._stop_flag.set()

    def _load_yolo(self):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "ultralytics is required for yolo_det_v1 plugin, please install it in the plugin environment"
            ) from exc
        return YOLO

    def _run_train_sync(
        self,
        *,
        workspace: WorkspaceProtocol,
        dataset_yaml: Path,
        base_model: str,
        epochs: int,
        batch: int,
        imgsz: int,
        patience: int,
        device: Any,
        train_seed: int,
        deterministic: bool,
        yolo_task: str = "obb",
        epoch_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return run_train_sync(
            workspace=workspace,
            dataset_yaml=dataset_yaml,
            base_model=base_model,
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            patience=patience,
            device=device,
            train_seed=train_seed,
            deterministic=deterministic,
            stop_flag=self._stop_flag,
            load_yolo=self._load_yolo,
            ensure_cjk_plot_font=self._ensure_cjk_plot_font,
            normalize_metrics=self._normalize_metrics,
            to_float=to_float,
            to_int=to_int,
            yolo_task=yolo_task,
            epoch_callback=epoch_callback,
        )

    def _ensure_cjk_plot_font(self) -> None:
        if self._font_setup_done:
            return
        with self._font_setup_lock:
            if self._font_setup_done:
                return
            try:
                import matplotlib  # type: ignore
                from matplotlib import font_manager  # type: ignore
            except Exception:
                self._font_setup_done = True
                return

            available_fonts = {str(item.name or "").strip() for item in font_manager.fontManager.ttflist}
            selected = next(
                (name for name in self._CJK_FONT_CANDIDATES if name in available_fonts),
                "",
            )
            if selected:
                sans_serif = [str(item) for item in matplotlib.rcParams.get("font.sans-serif", [])]
                merged = [selected, *[item for item in sans_serif if item != selected]]
                matplotlib.rcParams["font.family"] = ["sans-serif"]
                matplotlib.rcParams["font.sans-serif"] = merged
                matplotlib.rcParams["axes.unicode_minus"] = False
            else:
                warnings.warn(
                    "No CJK font found for matplotlib plots. Install one of: "
                    + ", ".join(self._CJK_FONT_CANDIDATES),
                    RuntimeWarning,
                    stacklevel=2,
                )
            self._font_setup_done = True

    def _normalize_metrics(self, raw: dict[str, Any] | Any) -> dict[str, float]:
        return normalize_metrics_row(raw, to_float)

    def _parse_results_csv(self, path: Path) -> list[dict[str, float]]:
        return parse_results_csv_rows(path, to_float)

    def _write_training_report(
        self,
        *,
        workspace: WorkspaceProtocol,
        metrics: dict[str, Any],
        train_result: dict[str, Any],
        prepare_stats: dict[str, Any],
    ) -> Path:
        report_path = workspace.artifacts_dir / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "metrics": metrics,
                    "history": train_result["history"],
                    "train_dir": str(train_result["save_dir"]),
                    "data_stats": prepare_stats,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report_path

    def _build_train_output(
        self,
        *,
        metrics: dict[str, Any],
        train_result: dict[str, Any],
        report_path: Path,
    ) -> TrainOutput:
        best_path = Path(train_result["best_path"])
        extra_artifacts: list[TrainArtifact] = list(train_result.get("extra_artifacts", []))
        return TrainOutput(
            metrics=metrics,
            artifacts=[
                TrainArtifact(
                    kind="weights",
                    name="best.pt",
                    path=best_path,
                    content_type="application/octet-stream",
                    required=True,
                ),
                TrainArtifact(
                    kind="report",
                    name="report.json",
                    path=report_path,
                    content_type="application/json",
                    required=True,
                ),
                *extra_artifacts,
            ],
        )
