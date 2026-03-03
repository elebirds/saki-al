from __future__ import annotations

from pathlib import Path

from saki_executor.plugins.external_handle import ExternalPluginDescriptor
from saki_executor.steps.orchestration.plugin_resolution_service import PluginResolutionService
from saki_plugin_sdk import PluginManifest


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
