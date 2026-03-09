# saki-dispatcher

`saki-dispatcher` 是 Saki 的运行时调度服务，负责 task 派发、编排推进、executor 连接管理以及与 API 的 runtime-domain 桥接。

## 1. 模块定位

负责：

1. runtime gRPC 服务：executor 注册、心跳、任务派发。
2. admin gRPC 服务：供 API 或运维入口控制。
3. 调度扫描与状态推进。
4. 与 API runtime-domain 的内部桥接调用。

不负责：

- 业务域 HTTP API。
- 实际模型训练执行。

## 2. 技术栈

- Go 1.24+
- gRPC
- PostgreSQL（通过 sqlc 访问）

## 3. 目录概览

```text
saki-dispatcher/
├── cmd/dispatcher/
├── internal/config/
├── internal/controlplane/
├── internal/dispatch/
├── internal/repo/
├── internal/server/
└── internal/gen/
```

## 4. 常用命令

```bash
make run
make test
make build
make fmt
make vet
make sqlc
make grpc
```

## 5. 关键环境变量

### 5.1 必要项

- `DATABASE_URL`
- `RUNTIME_GRPC_BIND`
- `ADMIN_GRPC_BIND`

### 5.2 鉴权与桥接

- `INTERNAL_TOKEN`
- `RUNTIME_DOMAIN_TARGET`
- `RUNTIME_DOMAIN_TOKEN`

### 5.3 调度行为

- `DISPATCH_SCAN_INTERVAL_SEC`
- `RUNTIME_HEARTBEAT_TIMEOUT_SEC`
- `ASSIGN_ACK_TIMEOUT_SEC`
- `ROUND_AFFINITY_WAIT_SEC`

## 6. 运行特性

1. runtime/admin 端口独立监听。
2. 可选 STDIN 命令台（`ENABLE_STDIN_COMMANDS`）。
3. 支持优雅停机和超时强制停机。

## 7. 契约约束

1. 以 `task` 为派发主干。
2. 与 API 的桥接失败会影响状态收敛，应优先修复。
3. 内部 token 校验基于 `x-internal-token`。

## 8. 排障建议

1. executor 无法注册
- 检查 runtime 端口监听与 token。

2. 任务不推进
- 检查 DB 连通与调度扫描日志。

3. API 侧看不到运行态回写
- 检查 `RUNTIME_DOMAIN_TARGET` 与 API runtime-domain 服务可达性。
