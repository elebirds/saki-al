# saki-executor 设计说明（当前实现）

## 1. 目标与边界

`saki-executor` 是运行在 GPU 机器上的主动学习执行器，负责：

1. 主动连接 `saki-api` 的 gRPC 控制面并维持心跳。
2. 接收训练任务、拉取训练数据、执行训练与选样。
3. 持续回传事件（日志/进度/指标）与任务结果（终态/候选样本/制品）。
4. 通过预签名 URL 上传制品到对象存储。

边界约束：

1. 不直接连接数据库。
2. 不直接连接前端。
3. 仅与 `saki-api`（gRPC）和对象存储预签名 URL 通信。

---

## 2. 当前目录结构（核心部分）

```text
saki-executor/
├── src/saki_executor/
│   ├── main.py                     # 启动入口：日志、组件装配、命令系统、生命周期管理
│   ├── core/
│   │   ├── config.py               # 配置项（环境变量）
│   │   └── logging.py              # 统一日志初始化（控制台 + 文件滚动）
│   ├── agent/
│   │   └── client.py               # gRPC 双向流客户端（注册、心跳、收发控制消息）
│   ├── jobs/
│   │   ├── state.py                # 执行器/任务状态枚举
│   │   ├── workspace.py            # runs/{job_id} 工作目录管理
│   │   └── manager.py              # 任务调度执行核心（单任务串行）
│   ├── cache/
│   │   └── asset_cache.py          # 样本缓存（内容寻址 + LRU）
│   ├── plugins/
│   │   ├── base.py                 # 插件统一接口
│   │   ├── registry.py             # 插件注册中心
│   │   └── builtin/demo_det/plugin.py  # 内置 demo 插件
│   ├── strategies/
│   │   └── builtin.py              # 内置选样策略
│   ├── sdk/
│   │   └── reporter.py             # 事件序列化与本地 events.jsonl
│   └── commands/
│       └── server.py               # 本地命令系统（stdin）
└── tests/
    └── test_strategies.py
```

---

## 3. 启动与生命周期

启动入口：`src/saki_executor/main.py`

启动流程：

1. 初始化日志系统（控制台 + `logs/executor.log` 滚动文件）。
2. 加载内置插件并创建缓存、任务管理器、gRPC 客户端。
3. 创建 `shutdown_event`，注册 `SIGINT/SIGTERM`。
4. 启动两个并发任务：
   - gRPC 客户端循环（`AgentClient.run`）
   - 命令系统循环（`CommandServer.run`）
5. 任一任务异常退出或收到退出命令后，触发统一退出流程并取消剩余任务。

---

## 4. gRPC 通信模型（JSON over stream）

### 4.1 上行消息（executor -> api）

1. `register`
2. `heartbeat`
3. `ack`
4. `job_event`
5. `job_result`
6. `data_request`
7. `upload_ticket_request`

### 4.2 下行消息（api -> executor）

1. `ack`
2. `assign_job`
3. `stop_job`
4. `data_response`
5. `upload_ticket_response`
6. `error`

### 4.3 NAT 适配

执行器主动发起连接，API 不需要反向连接执行器，因此可运行在 NAT/内网 GPU 机器。

---

## 5. 状态机（当前实现）

### 5.1 执行器状态（`ExecutorState`）

`OFFLINE -> CONNECTING -> IDLE -> RESERVED -> RUNNING -> FINALIZING -> IDLE`

异常恢复路径：

`CONNECTING/RUNNING -> ERROR_RECOVERY -> OFFLINE/CONNECTING`

### 5.2 任务状态（内部）

`CREATED -> QUEUED -> RUNNING -> {SUCCEEDED|FAILED|STOPPED}`

`JobManager` 维护：

1. `current_job_id`
2. `last_job_id`
3. `last_job_status`

并提供 `status_snapshot()` 供命令系统查询。

---

## 6. 任务执行主流程（`JobManager`）

1. 接收 `assign_job`，检查是否忙碌（单任务串行）。
2. 创建工作目录 `runs/{job_id}`，写入 `config.json`。
3. 分页拉取 `labels/samples/annotations/unlabeled_samples`。
4. 下载样本到本地缓存（按 `asset_hash` 内容寻址）。
5. 调用插件：
   - `validate_params`
   - `prepare_data`
   - `train`
   - `predict_unlabeled`
6. 逐个制品申请上传票据并 PUT 上传对象存储。
7. 回传 `job_result`（终态、指标、制品、TopK 候选）。
8. 收尾：状态回到 `IDLE`。

停止流程：

1. 收到 `stop_job` 后触发 `_stop_event`。
2. 调用插件 `stop(job_id)`（best-effort）。
3. 任务协程转为 `STOPPED` 并上报结果。
4. 对已终态任务再次 stop 视为幂等成功。

---

## 7. 缓存设计（`AssetCache`）

缓存键：`asset_hash`

路径：`cache/assets/<hash_prefix>/<asset_hash>`

索引：`cache/cache_index.json`，记录：

1. `size`
2. `last_access`
3. `pin_job_id`（当前任务保护）

策略：

1. 下载后做 SHA256 校验，不一致则丢弃。
2. 超阈值时按 LRU 淘汰，并尽量避开当前任务 pinned 资源。

---

## 8. 插件与策略体系

### 8.1 插件接口（`plugins/base.py`）

统一接口：

1. `validate_params`
2. `prepare_data`
3. `train`
4. `predict_unlabeled`
5. `stop`

### 8.2 内置策略（`strategies/builtin.py`）

1. `uncertainty_1_minus_max_conf`
2. `aug_iou_disagreement`
3. `random_baseline`
4. `plugin_native_strategy`

---

## 9. 日志系统（新增）

入口：`core/logging.py`

特性：

1. 统一格式：`时间 | 级别 | 模块 | 消息`
2. 控制台输出 + 滚动文件输出
3. 启动时输出关键信息：`executor_id`、版本、gRPC 目标、加载插件
4. 关键链路有日志：连接、注册、心跳、派发、停止、任务成功/失败

默认日志文件：`logs/executor.log`

---

## 10. 命令系统（新增）

入口：`commands/server.py`，默认通过标准输入读取命令。

可用命令：

1. `help`：查看命令列表
2. `status`：查看执行器状态、当前任务、请求队列、最近心跳
3. `plugins`：查看已加载插件与能力
4. `connect`：启用并发起连接
5. `disconnect`：断开并暂停连接
6. `stop [job_id]`：停止当前任务或指定任务
7. `loglevel <LEVEL>`：动态调整日志级别
8. `quit|exit`：触发优雅退出

---

## 11. 配置项（`core/config.py`）

基础：

1. `EXECUTOR_ID`
2. `EXECUTOR_VERSION`
3. `API_GRPC_TARGET`
4. `INTERNAL_TOKEN`
5. `HEARTBEAT_INTERVAL_SEC`

存储与资源：

1. `RUNS_DIR`
2. `CACHE_DIR`
3. `CACHE_MAX_BYTES`
4. `DEFAULT_GPU_IDS`
5. `CPU_WORKERS`
6. `MEMORY_MB`

日志与命令：

1. `LOG_LEVEL`
2. `LOG_DIR`
3. `LOG_FILE_NAME`
4. `LOG_MAX_BYTES`
5. `LOG_BACKUP_COUNT`
6. `ENABLE_COMMAND_STDIN`

---

## 12. 运行方式

```bash
cd saki-executor
uv sync
uv run python -m saki_executor.main
```

启动后可在当前终端直接输入命令（如 `status`、`help`）。

---

## 13. 当前已知限制

1. gRPC 仍为 JSON over stream，尚未切换 pb2 强类型收发。
2. 插件训练仍以 demo 形态为主，未接真实大模型训练栈。
3. 命令系统目前为本地 stdin 通道，尚未提供远程管理端口。
4. 单执行器固定单任务串行，扩展依赖多实例部署。
