import json
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from saki_runtime.core.client import saki_client
from saki_runtime.jobs.interfaces import PluginAdapter
from saki_runtime.jobs.workspace import Workspace
from saki_runtime.plugins.base import PluginBase


class DemoAdapter(PluginAdapter):
    @property
    def trainer_entrypoint(self) -> str:
        return "saki_runtime.plugins.builtin.demo_plugin.train_entry"

    def validate_params(self, params: Dict[str, Any]) -> None:
        # Simple validation for MVP
        required = ["epochs", "batch_size"]
        for req in required:
            if req not in params:
                raise ValueError(f"Missing required param: {req}")

    async def prepare(self, workspace: Workspace, params: Dict[str, Any]) -> None:
        logger.info(f"Preparing data for job {workspace.job_id}...")
        
        # Load config to get data ref
        config = workspace.load_config()
        if not config:
            raise ValueError("Config not found")
            
        data_ref = config["data_ref"]
        dataset_version_id = data_ref["dataset_version_id"]
        label_version_id = data_ref["label_version_id"]

        # 1. Fetch Labels
        # Note: get_labels takes project_id, but data_ref only has versions.
        # We need project_id from config.
        project_id = config["project_id"]
        labels = await saki_client.get_labels(project_id)
        
        # Write labels.txt
        labels_path = workspace.data_dir / "labels.txt"
        with open(labels_path, "w") as f:
            for label in labels:
                f.write(f"{label.name}\n")

        # 2. Fetch Annotations & Samples
        # For MVP, we'll just create a manifest and dummy files structure
        # Real implementation would download images and convert annotations to YOLO format
        
        images_dir = workspace.data_dir / "images"
        labels_dir = workspace.data_dir / "labels"
        images_dir.mkdir(exist_ok=True)
        labels_dir.mkdir(exist_ok=True)

        manifest = []
        
        # Fetch annotations
        async for ann in saki_client.iter_annotations(label_version_id):
            # In real world:
            # 1. Find corresponding sample (need sample cache or fetch)
            # 2. Convert bbox to YOLO format
            # 3. Write to labels_dir/{sample_id}.txt
            pass
            
        # Fetch samples (for images)
        async for sample in saki_client.iter_samples(dataset_version_id):
            # In real world: download image to images_dir
            manifest.append({"id": sample.id, "uri": sample.uri})

        # Write manifest
        with open(workspace.data_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
            
        logger.info(f"Data preparation complete for job {workspace.job_id}")


class DemoPlugin(PluginBase):
    @property
    def id(self) -> str:
        return "demo_plugin"

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
                    "learning_rate": {"type": "number", "default": 0.01}
                },
                "required": ["epochs", "batch_size"]
            }
        return {}

    def get_adapter(self) -> PluginAdapter:
        return DemoAdapter()
