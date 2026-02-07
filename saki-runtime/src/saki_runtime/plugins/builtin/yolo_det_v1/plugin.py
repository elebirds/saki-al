import json
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from saki_runtime.core.client import saki_client
from saki_runtime.jobs.interfaces import PluginAdapter
from saki_runtime.jobs.workspace import Workspace
from saki_runtime.plugins.base import PluginBase


class YoloDetAdapter(PluginAdapter):
    @property
    def trainer_entrypoint(self) -> str:
        return "saki_runtime.plugins.builtin.yolo_det_v1.train_entry"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> list[str]:
        return ["train_detection"]

    def validate_params(self, params: Dict[str, Any]) -> None:
        required = ["epochs", "batch_size"]
        for req in required:
            if req not in params:
                raise ValueError(f"Missing required param: {req}")

    async def prepare(self, workspace: Workspace, params: Dict[str, Any]) -> None:
        logger.info(f"Preparing data for job {workspace.job_id}...")
        config = workspace.load_config()
        if not config:
            raise ValueError("Config not found")

        commit_id = config["source_commit_id"]
        project_id = config["project_id"]

        labels = await saki_client.get_labels(project_id)

        # Minimal manifest; real adapter should convert to YOLO format.
        samples = []
        async for sample in saki_client.iter_samples(commit_id):
            samples.append({"id": sample.id, "uri": sample.uri})

        annotations = []
        async for ann in saki_client.iter_annotations(commit_id):
            annotations.append(ann.model_dump())

        manifest = {
            "task_type": "detection",
            "format": "yolo",
            "source_commit_id": commit_id,
            "num_samples": len(samples),
            "num_annotations": len(annotations),
            "labels": [label.model_dump() for label in labels],
        }

        workspace.data_dir.mkdir(exist_ok=True, parents=True)
        with open(workspace.data_dir / "dataset_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        with open(workspace.data_dir / "samples.json", "w") as f:
            json.dump(samples, f, indent=2)

        with open(workspace.data_dir / "annotations.json", "w") as f:
            json.dump(annotations, f, indent=2)

        logger.info(f"Data preparation complete for job {workspace.job_id}")


class YoloDetPlugin(PluginBase):
    @property
    def id(self) -> str:
        return "yolo_det_v1"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> List[str]:
        return ["train_detection"]

    def get_schema(self, op: str) -> Dict[str, Any]:
        if op == "train":
            return {
                "type": "object",
                "properties": {
                    "epochs": {"type": "integer", "default": 10},
                    "batch_size": {"type": "integer", "default": 16},
                    "learning_rate": {"type": "number", "default": 0.01},
                },
                "required": ["epochs", "batch_size"],
            }
        if op == "query":
            return {
                "type": "object",
                "properties": {
                    "max_images": {"type": "integer", "default": 5000},
                },
            }
        return {}

    def get_adapter(self) -> PluginAdapter:
        return YoloDetAdapter()
