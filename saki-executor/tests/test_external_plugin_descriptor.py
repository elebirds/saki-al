from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from saki_executor.plugins.external_handle import ExternalPluginDescriptor
from saki_executor.steps.contracts import StepExecutionRequest
from saki_executor.steps.orchestration.plugin_resolution_service import PluginResolutionService
from saki_plugin_sdk import HostCapabilitySnapshot, PluginManifest


def test_external_plugin_descriptor_is_metadata_only(tmp_path: Path):
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "descriptor_only_plugin",
            "version": "3.1.0",
            "display_name": "Descriptor Only Plugin",
            "supported_step_types": ["train"],
            "supported_strategies": ["uncertainty_1_minus_max_conf"],
            "runtime_profiles": [
                {
                    "id": "cpu",
                    "priority": 100,
                    "when": "host.backends.includes('cpu')",
                    "dependency_groups": ["profile-cpu"],
                    "allowed_backends": ["cpu"],
                }
            ],
            "config_schema": {
                "title": "Descriptor Config",
                "fields": [
                    {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1},
                ],
            },
            "entrypoint": "dummy.worker:main",
        }
    )

    descriptor = ExternalPluginDescriptor(
        manifest=manifest,
        plugin_dir=tmp_path,
        python_path=Path(__file__),
    )

    assert descriptor.plugin_id == "descriptor_only_plugin"
    assert hasattr(descriptor, "validate_params")
    assert not hasattr(descriptor, "train")
    assert not hasattr(descriptor, "eval")
    assert not hasattr(descriptor, "predict")


def test_plugin_resolution_accepts_descriptor_runtime_profile_specs(tmp_path: Path):
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "descriptor_profile_plugin",
            "version": "3.1.0",
            "display_name": "Descriptor Profile Plugin",
            "supported_step_types": ["train"],
            "supported_strategies": ["uncertainty_1_minus_max_conf"],
            "runtime_profiles": [
                {
                    "id": "cpu",
                    "priority": 100,
                    "when": "host.backends.includes('cpu')",
                    "dependency_groups": ["profile-cpu"],
                    "allowed_backends": ["cpu"],
                }
            ],
            "entrypoint": "dummy.worker:main",
        }
    )
    descriptor = ExternalPluginDescriptor(
        manifest=manifest,
        plugin_dir=tmp_path,
        python_path=Path(__file__),
    )

    profiles = PluginResolutionService._resolve_runtime_profiles(descriptor)  # noqa: SLF001
    assert len(profiles) == 1
    assert profiles[0].id == "cpu"


def test_plugin_resolution_passes_deterministic_level_and_strong_flag(tmp_path: Path):
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "descriptor_resolve_plugin",
            "version": "3.1.0",
            "display_name": "Descriptor Resolve Plugin",
            "supported_step_types": ["train"],
            "supported_strategies": ["random_baseline"],
            "runtime_profiles": [
                {
                    "id": "cpu",
                    "priority": 100,
                    "when": "host.backends.includes('cpu')",
                    "dependency_groups": ["profile-cpu"],
                    "allowed_backends": ["cpu"],
                }
            ],
            "config_schema": {
                "title": "Descriptor Config",
                "fields": [
                    {"key": "epochs", "label": "Epochs", "type": "integer", "default": 1},
                ],
            },
            "entrypoint": "dummy.worker:main",
        }
    )
    descriptor = ExternalPluginDescriptor(
        manifest=manifest,
        plugin_dir=tmp_path,
        python_path=Path(__file__),
    )

    class _Registry:
        def __init__(self, plugin: ExternalPluginDescriptor) -> None:
            self._plugin = plugin

        def get(self, plugin_id: str):
            if plugin_id == self._plugin.plugin_id:
                return self._plugin
            return None

        def ensure_worker_loadable(self, plugin_id: str) -> None:
            del plugin_id
            return None

    manager = SimpleNamespace(
        plugin_registry=_Registry(descriptor),
        get_host_capability_snapshot=lambda: HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 8192,
                "gpus": [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        ),
    )
    request = StepExecutionRequest(
        step_id="step-1",
        round_id="round-1",
        step_type="train",
        dispatch_kind="dispatchable",
        plugin_id=descriptor.plugin_id,
        resolved_params={
            "plugin": {},
            "deterministic_level": "strong_deterministic",
            "deterministic": True,
            "strong_deterministic": True,
        },
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="active_learning",
        round_index=1,
        attempt=1,
        depends_on_step_ids=[],
        raw_payload={},
    )

    plan = PluginResolutionService().resolve(manager=manager, request=request)
    assert plan.effective_plugin_params["deterministic_level"] == "strong_deterministic"
    assert plan.effective_plugin_params["deterministic"] is True
    assert plan.effective_plugin_params["strong_deterministic"] is True
