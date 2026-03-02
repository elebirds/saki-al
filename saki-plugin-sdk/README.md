# saki-plugin-sdk v2

`saki-plugin-sdk` 是 Saki 插件体系的唯一公共能力层（V2）。

## V2 核心约束

1. `ExecutorPlugin` 是唯一插件契约。
2. 所有执行方法必须接收 `context: StepRuntimeContext`。
3. IPC 协议固定为 v2（`protocol_version=2`）。
4. 共享能力统一由 SDK 提供：
   - `StepReporter`
   - `ipc.protocol` / `ipc.worker`
   - `strategies` / `aug_iou`
   - `hardware`（设备探测与归一化）
   - `data_split`（训练/验证划分）

## 插件开发最小示例

```python
from __future__ import annotations
from typing import Any

from saki_plugin_sdk import (
    EventCallback,
    ExecutorPlugin,
    StepRuntimeContext,
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
        context: StepRuntimeContext,
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
        context: StepRuntimeContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []
```

## 配置与校验

`ExecutorPlugin` 默认提供：

1. `request_config_schema`
2. `default_request_config`
3. `resolve_config(...)`
4. `validate_params(...)`

默认实现基于 `plugin.yml` 的 `config_schema/default_config`，插件可按需覆写。

## Worker 协议

1. Worker 入站命令统一走 `saki_plugin_sdk.ipc.protocol`。
2. 非 `ping` action 必须携带 `payload.context`。
3. Worker 遇到非 v2 协议直接返回错误，不提供 v1 兼容层。
