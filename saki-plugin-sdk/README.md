# saki-plugin-sdk v3

`saki-plugin-sdk` 是 Saki 插件体系的唯一公共能力层（V3）。

## V3 核心约束

1. `ExecutorPlugin` 是唯一插件契约。
2. 执行方法必须接收 `context: ExecutionBindingContext`。
3. IPC 协议固定为 v3（`protocol_version=3`）。
4. 共享能力统一由 SDK 提供：
   - `TaskReporter`
   - `ipc.protocol` / `ipc.worker`
   - `strategies` / `aug_iou`
   - `capability_types` / `profile_spec` / `binding_policy`（纯规则与类型）
   - `data_split`（训练/验证划分）
5. SDK 不承载宿主硬件探测副作用实现。

## 插件开发最小示例

```python
from __future__ import annotations
from typing import Any

from saki_plugin_sdk import (
    ExecutionBindingContext,
    EventCallback,
    ExecutorPlugin,
    TrainOutput,
    Workspace,
)


class MyPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = self._load_manifest()

    async def train(
        self,
        workspace: Workspace,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        del workspace, params, emit, context
        return TrainOutput(metrics={}, artifacts=[])

    async def predict_unlabeled(
        self,
        workspace: Workspace,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []
```

## 配置与校验

`ExecutorPlugin` 默认提供：

1. `request_config_schema`
2. `resolve_config(...)`
3. `validate_params(...)`

默认实现基于 `plugin.yml` 的 `config_schema`，插件可按需覆写。
配置模型仅保留 `PluginConfig.resolve(...)`、`PluginConfig.from_manifest(...)` 与 `PluginConfig.model_validate(...)` 三条入口。

## Worker 协议

1. Worker 入站命令统一走 `saki_plugin_sdk.ipc.protocol`。
2. `prepare/train/eval/predict*` 需要 `payload.execution_binding_context`。
3. Worker 遇到非 v3 协议直接返回错误，不提供兼容层。
