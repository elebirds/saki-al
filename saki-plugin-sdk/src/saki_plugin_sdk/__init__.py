"""Saki Plugin SDK – base classes, IPC protocol, workspace utilities, and built-in strategies."""

from saki_plugin_sdk.base import (
    EventCallback,
    ExecutorPlugin,
    TrainArtifact,
    TrainOutput,
    StepRuntimeRequirements,
    default_step_runtime_requirements,
    resolve_step_runtime_requirements,
)
from saki_plugin_sdk.types import StepRuntimeContext
from saki_plugin_sdk.capability_types import HostCapabilitySnapshot, RuntimeCapabilitySnapshot, GpuDeviceCapability
from saki_plugin_sdk.profile_spec import RuntimeProfileSpec, parse_runtime_profiles
from saki_plugin_sdk.device_binding import DeviceBinding
from saki_plugin_sdk.execution_binding_context import ExecutionBindingContext
from saki_plugin_sdk.binding_policy import DevicePriorityStrategy, normalize_backend_name, resolve_device_binding
from saki_plugin_sdk.specification import evaluate_profile_spec
from saki_plugin_sdk.config import (
    PluginConfig,
    ConfigSchema,
    ConfigField,
    ConfigFieldOption,
    ConfigFieldProps,
)
from saki_plugin_sdk.workspace import Workspace
from saki_plugin_sdk.workspace_protocol import WorkspaceProtocol
from saki_plugin_sdk.reporter import StepReporter
from saki_plugin_sdk.manifest import PluginManifest
from saki_plugin_sdk.logger import PluginLogger
from saki_plugin_sdk.exceptions import (
    PluginError,
    PluginConfigError,
    PluginValidationError,
    PluginLifecycleError,
)
from saki_plugin_sdk.cond import (
    evaluate_visible,
    filter_options,
)
from saki_plugin_sdk.data_split import resolve_train_val_split
from saki_ir import normalize_prediction_candidates

__all__ = [
    # Base classes
    "EventCallback",
    "ExecutorPlugin",
    "TrainArtifact",
    "TrainOutput",
    "StepRuntimeRequirements",
    "default_step_runtime_requirements",
    "resolve_step_runtime_requirements",
    "StepRuntimeContext",
    "HostCapabilitySnapshot",
    "RuntimeCapabilitySnapshot",
    "GpuDeviceCapability",
    "RuntimeProfileSpec",
    "parse_runtime_profiles",
    "DeviceBinding",
    "ExecutionBindingContext",
    "DevicePriorityStrategy",
    "normalize_backend_name",
    "resolve_device_binding",
    "evaluate_profile_spec",
    # Configuration
    "PluginConfig",
    "ConfigSchema",
    "ConfigField",
    "ConfigFieldOption",
    "ConfigFieldProps",
    # Workspace & reporting
    "Workspace",
    "WorkspaceProtocol",
    "StepReporter",
    "PluginManifest",
    # Logging
    "PluginLogger",
    # Exceptions
    "PluginError",
    "PluginConfigError",
    "PluginValidationError",
    "PluginLifecycleError",
    # Expression evaluation
    "evaluate_visible",
    "filter_options",
    # Shared runtime utilities
    "resolve_train_val_split",
    "normalize_prediction_candidates",
]
