"""Saki Plugin SDK – base classes, IPC protocol, workspace utilities, and built-in strategies."""

from saki_plugin_sdk.base import EventCallback, ExecutorPlugin, TrainArtifact, TrainOutput, StepRuntimeRequirements
from saki_plugin_sdk.config import (
    PluginConfig,
    ConfigSchema,
    ConfigField,
    ConfigFieldOption,
    ConfigFieldOptionCond,
    ConfigFieldUI,
    ConfigFieldProps,
)
from saki_plugin_sdk.workspace import Workspace
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

__all__ = [
    # Base classes
    "EventCallback",
    "ExecutorPlugin",
    "TrainArtifact",
    "TrainOutput",
    "StepRuntimeRequirements",
    # Configuration
    "PluginConfig",
    "ConfigSchema",
    "ConfigField",
    "ConfigFieldOption",
    "ConfigFieldOptionCond",
    "ConfigFieldUI",
    "ConfigFieldProps",
    # Workspace & reporting
    "Workspace",
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
]
