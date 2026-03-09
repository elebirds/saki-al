# saki-plugin-sdk

`saki-plugin-sdk` 是 Saki 插件体系的统一公共层，负责定义插件契约、IPC 协议和通用能力。

## 1. 模块定位

SDK 提供：

1. `ExecutorPlugin` 基类与类型定义。
2. worker IPC 协议与消息结构。
3. 任务上报能力（事件、指标、产物）。
4. 通用策略与工具能力。

SDK 不提供：

- 具体模型训练逻辑。
- dispatcher/api 业务域能力。

## 2. 版本与兼容

- 当前版本：`4.0.0`
- Python：`>=3.11`
- 下游插件需在 `plugin.yml` 声明：`sdk_version: ">=4.0.0"`

## 3. 最小插件骨架

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
```

## 4. 开发命令

```bash
cd saki-plugin-sdk
uv sync --extra dev
uv run pytest
```

## 5. 契约要点

1. 插件入口由 `plugin.yml -> entrypoint` 声明。
2. 运行能力由 `runtime_profiles` 声明。
3. 参数 schema 由 `config_schema` 声明。
4. 宿主注入执行上下文，插件只关心算法逻辑。

## 6. 与执行器关系

- 执行器负责插件发现、profile 选择、worker 生命周期。
- SDK 负责插件接口标准化与 IPC 协议标准化。

## 7. 文档

- 配置 schema 细节：`PLUGIN_CONFIG_GUIDE.md`
