# saki-executor 设计说明（V3）

## 1. 目标与边界

`saki-executor` 在 V3 中只承担运行时宿主职责：

1. 调度与状态机（任务接收、停止、收尾）
2. 数据拉取与样本缓存
3. 宿主硬件探测、runtime profile 选择、profile 虚拟环境管理
4. 设备绑定决策与失败前置校验
5. 插件 worker 子进程管理与事件桥接
6. 制品上传与结果回传

不再承载任何“插件公共实现”。

## 2. 职责分层

1. `saki-plugin-sdk`
   - 插件基类 `ExecutorPlugin`
   - `StepRuntimeContext`
   - `ExecutionBindingContext`
   - IPC 协议与 worker 框架
   - `StepReporter`
   - 策略算法、profile/binding 纯规则、split 工具
2. `saki-executor`
   - 编排与宿主运行时
   - IPC 客户端、外部插件发现、消息网桥
3. `saki-plugins/*`
   - 插件特有业务逻辑（模型训练/评估/预测）

## 3. 关键执行链路

1. `StepPipelineRunner` 先构造 `StepRuntimeContext`，再完成 Host/Runtime capability 采集
2. 基于 `runtime_profiles` 选择 profile 并创建/复用 `.venv-<profile_id>`
3. 通过 `DeviceBindingResolver` 生成 `ExecutionBindingContext`
4. 通过 `SubprocessPluginProxy` 调用插件 worker
5. 统一以 `execution_binding_context + params` 传递运行时信息
4. `StepEventEmitter` 通过 SDK `StepReporter` 生成事件
5. `StepManager` 负责终态与制品上传

V3 已移除 executor 中对插件特化参数的注入逻辑（例如 `splits.yolo_task` 注入）。

## 4. IPC 协议（V3）

1. 命令包必须带 `protocol_version=3`
2. 新增 `probe_runtime_capability`、`bind_execution_context`
3. 执行动作必须带 `payload.execution_binding_context`
4. worker 对非 v3 请求直接报错

## 5. 目录摘要（V3）

```text
src/saki_executor/
├── agent/                     # gRPC 客户端
├── cache/                     # 样本缓存
├── plugins/
│   ├── external_handle.py     # manifest 元数据句柄
│   ├── ipc/
│   │   ├── client.py          # worker 客户端
│   │   └── proxy_plugin.py    # ExecutorPlugin 代理
│   └── registry.py
├── runtime/
│   ├── capability/            # host capability probe
│   ├── profile/               # runtime profile selector
│   ├── environment/           # profile venv factory / installer
│   └── binding/               # device binding resolver
├── steps/
│   ├── manager.py
│   ├── orchestration/
│   │   ├── runner.py
│   │   ├── event_emitter.py
│   │   └── training_data_service.py
│   └── services/
│       ├── sampling_service.py
│       └── artifact_uploader.py
└── core/
    └── config.py
```

## 6. 版本约定

V3 主版本：

1. `saki-plugin-sdk`: `3.x`
2. `saki-executor`: `3.x`
3. 内置插件（如 demo / yolo）与 SDK 同窗口升级到 `3.x`
