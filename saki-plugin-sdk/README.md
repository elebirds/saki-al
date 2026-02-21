# saki-plugin-sdk

Plugin SDK for the Saki executor platform. Provides base classes, IPC protocol, workspace utilities, and built-in sampling strategies for developing Saki plugins.

## Installation

```bash
uv sync
```

## Usage

Plugins should inherit from `saki_plugin_sdk.ExecutorPlugin` and implement the required methods. Each plugin ships with a `plugin.yml` manifest and a worker entry point that calls `saki_plugin_sdk.ipc.worker.run_worker(plugin)`.
