# saki-executor 设计说明（V2）

## 1. 目标与边界

`saki-executor` 在 V2 中只承担运行时宿主职责：

1. 调度与状态机（任务接收、停止、收尾）
2. 数据拉取与样本缓存
3. 插件 worker 子进程管理与事件桥接
4. 制品上传与结果回传

不再承载任何“插件公共实现”。

## 2. 职责分层

1. `saki-plugin-sdk`
   - 插件基类 `ExecutorPlugin`
   - `StepRuntimeContext`
   - IPC 协议与 worker 框架
   - `StepReporter`
   - 策略算法、硬件探测、split 工具
2. `saki-executor`
   - 编排与宿主运行时
   - IPC 客户端、外部插件发现、消息网桥
3. `saki-plugins/*`
   - 插件特有业务逻辑（模型训练/评估/预测）

## 3. 关键执行链路

1. `StepPipelineRunner` 解析请求并构造 `StepRuntimeContext`
2. 通过 `SubprocessPluginProxy` 调用插件 worker
3. 统一以 `context + params` 传递运行时信息
4. `StepEventEmitter` 通过 SDK `StepReporter` 生成事件
5. `StepManager` 负责终态与制品上传

V2 已移除 executor 中对插件特化参数的注入逻辑（例如 `splits.yolo_task` 注入）。

## 4. IPC 协议（V2）

1. 命令包必须带 `protocol_version=2`
2. 非 `ping` action 必须带 `payload.context`
3. worker 对非 v2 请求直接报错

## 5. 目录摘要（V2）

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

V2 主版本：

1. `saki-plugin-sdk`: `2.x`
2. `saki-executor`: `2.x`
3. 内置插件（如 demo / yolo）与 SDK 同窗口升级到 `2.x`
