# Saki

Saki 是一个面向视觉主动学习闭环的多模块仓库，覆盖数据导入、标注、制品管理、执行调度与前端工作台。

当前默认运行面已经切到 Go 版 `controlplane + agent`：

- `saki-controlplane`
  - `cmd/public-api`：对外 HTTP API
  - `cmd/runtime`：runtime roles（`ingress / scheduler / delivery / recovery`）
- `saki-agent`
  - agent 注册、心跳、命令领取、任务执行与事件回推
- `saki-web`
  - React 工作台

## 1. 当前架构

### 1.1 Runtime 基线

- 任务真相：`runtime_task`
- 派发真相：`task_assignment`
- 命令真相：`agent_command`
- delivery 模式：`direct / pull`，默认推荐 `pull`
- 恢复职责：由 `runtime recovery` role 独立处理 assign 未确认、agent 失联、cancel 收敛

### 1.2 仓库结构

```text
saki/
├── saki-controlplane/
├── saki-agent/
├── saki-web/
├── saki-plugin-sdk/
├── saki-plugins/
├── proto/
├── docs/
├── docker-compose.yml
└── env.example
```

### 1.3 迁移说明

- `saki-api`、`saki-dispatcher`、`saki-executor` 目录目前仍保留在仓库中，用于迁移参考和历史 Dockerfile。
- 默认开发入口、默认 `docker-compose.yml`、默认文档说明都已经切到 `saki-controlplane` 和 `saki-agent`。
- 若你仍在使用旧三段式进程模型，不要再把它当作当前主路径。

## 2. 快速开始

### 2.1 Docker Compose

当前 compose 面向本地开发，`saki-controlplane-public-api`、`saki-controlplane-runtime`、`saki-agent` 通过官方 Go 镜像直接 `go run` 启动；这是在专用 Dockerfile 落地前的过渡方案。

```bash
cp env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f saki-controlplane-public-api saki-controlplane-runtime saki-agent
```

默认端口：

- public API: `http://localhost:8000`
- runtime healthz: `http://localhost:8081/healthz`
- web: `http://localhost`
- minio: `http://localhost:9001`

### 2.2 本地开发

建议环境：

- Go `1.25+`
- Node.js `18+`
- PostgreSQL
- MinIO 或兼容 S3 存储

启动顺序建议：

1. public API

```bash
cd saki-controlplane
go run ./cmd/public-api
```

2. runtime

```bash
cd saki-controlplane
go run ./cmd/runtime
```

3. agent

```bash
cd saki-agent
go run ./cmd/agent
```

4. web

```bash
cd saki-web
npm install
npm run dev
```

## 3. 常用命令

- controlplane OpenAPI / proto / sqlc 生成：`cd saki-controlplane && make gen`
- controlplane 测试：`cd saki-controlplane && go test ./...`
- runtime 相关测试：`cd saki-controlplane && go test ./internal/modules/runtime/... -count=1`
- agent 测试：`cd saki-agent && go test ./...`
- web 构建：`cd saki-web && npm run build`

## 4. 关键环境变量

### 4.1 controlplane public-api

- `DATABASE_DSN`
- `PUBLIC_API_BIND`
- `AUTH_TOKEN_SECRET`
- `AUTH_TOKEN_TTL`
- `MINIO_*`

### 4.2 controlplane runtime

- `DATABASE_DSN`
- `RUNTIME_BIND`
- `RUNTIME_ROLES`
- `RUNTIME_ASSIGN_ACK_TIMEOUT`
- `RUNTIME_AGENT_HEARTBEAT_TIMEOUT`
- `MINIO_*`

### 4.3 agent

- `RUNTIME_BASE_URL`
- `AGENT_TRANSPORT_MODE`
- `AGENT_ID`
- `AGENT_VERSION`
- `AGENT_MAX_CONCURRENCY`
- `AGENT_HEARTBEAT_INTERVAL`
- `AGENT_WORKER_COMMAND_JSON`

## 5. Runtime 约束

1. 业务与任务真相由 controlplane 持有，agent 不直接改业务库。
2. `agent_command` 是命令真相，transport 只是投递方式，不得反向成为状态真相。
3. `runtime recovery` 必须独立于 scheduler，不能把超时收敛混入正常派发。
4. 对外 HTTP API 的 canonical 路径是 `/runtime/agents`，`/runtime/executors` 仅保留一个兼容窗口。

## 6. 常见问题

1. `runtime` 启动即退出

- 先检查 `DATABASE_DSN`。
- 再检查 `MINIO_*` 是否完整；runtime 会在启动时探测对象存储。

2. agent 注册不上

- 检查 `RUNTIME_BASE_URL` 是否指向 `saki-controlplane-runtime`。
- 检查 `AGENT_TRANSPORT_MODE` 是否与部署预期一致。

3. agent 接到任务后立刻失败

- 通常是 `AGENT_WORKER_COMMAND_JSON` 没配置，或配置的 worker 不符合协议。

4. `/runtime/executors` 和文档不一致

- 以 `/runtime/agents` 为主；`/runtime/executors` 是兼容 alias，会被移除。
