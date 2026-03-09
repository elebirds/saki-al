# saki-executor

`saki-executor` 是运行在执行节点上的任务执行器，主动连接 dispatcher，按 task 执行训练、评分、预测、评估等动作。

## 1. 模块定位

负责：

1. 接收并执行 `DISPATCHABLE` task。
2. 管理插件发现、profile 选择、worker 生命周期。
3. 回传事件、指标、候选、制品。

不负责：

- 业务数据库写入。
- 编排策略决策。

## 2. 依赖

- Python `>=3.11`
- `uv`
- `saki-plugin-sdk`
- 可选运行后端：`cuda`/`mps`/`cpu`

## 3. 目录概览

```text
saki-executor/src/saki_executor/
├── agent/
├── commands/
├── plugins/
├── runtime/
├── steps/
└── core/
```

## 4. 安装与运行

```bash
cd saki-executor
make sync
make run
```

测试：

```bash
make test
```

## 5. 关键环境变量

### 5.1 连接

- `API_GRPC_TARGET`
- `INTERNAL_TOKEN`
- `HEARTBEAT_INTERVAL_SEC`

### 5.2 本地目录

- `RUNS_DIR`
- `CACHE_DIR`
- `PLUGINS_DIR`

### 5.3 宿主与策略

- `CPU_WORKERS`
- `MEMORY_MB`
- `DEFAULT_GPU_IDS`
- `ROUND_SHARED_CACHE_ENABLED`
- `STRICT_TRAIN_MODEL_HANDOFF`

### 5.4 插件 worker

- `PLUGIN_VENV_AUTO_SYNC`
- `PLUGIN_WORKER_STARTUP_TIMEOUT_SEC`
- `PLUGIN_WORKER_TERM_TIMEOUT_SEC`

## 6. 命令台（STDIN）

启用 `ENABLE_COMMAND_STDIN=true` 后可用：

- `help`
- `status`
- `plugins`
- `connect`
- `disconnect [--force]`
- `stop [job_id]`
- `loglevel <LEVEL>`
- `quit` / `exit`

## 7. 跨模块契约

1. 任务主键以 `task_id` 为核心。
2. 执行器通过 gRPC 与对象存储 URL 和外部系统交互。
3. 业务落库与编排推进由 API/dispatcher 负责。

## 8. 排障建议

1. 一直重连 dispatcher
- 检查 `API_GRPC_TARGET` 与 token。

2. 插件未发现
- 检查 `PLUGINS_DIR` 下是否包含 `plugin.yml`。

3. 任务执行慢或失败
- 检查 profile 依赖安装、硬件可用性、worker 日志。

设计详见：`EXECUTOR_DESIGN.md`。
