# Saki

Saki 是一个面向视觉主动学习（Active Learning）闭环的多服务仓库，覆盖数据导入、标注、版本管理、训练、预测、选样与迭代全流程。

当前 Runtime 语义基线：

- 执行真相源：`task`
- 编排视图：`loop / round / step`
- 预测资源：`prediction`（循环外独立资源，绑定 `task_id`）

## 1. 项目目标

Saki 解决的是“标注成本高、迭代慢、实验难复现”问题，核心目标：

1. 在统一平台内完成数据与模型迭代闭环。
2. 将执行链路（训练/预测/选样）与业务链路（项目/标注/版本）解耦。
3. 用结构化事件与制品管理提高可观测性与可追溯性。

## 2. 仓库架构总览

### 2.1 运行时角色

- `saki-api`
  - 业务真相源（项目、分支、提交、标注、权限、导入导出）
  - Runtime 领域 API
  - Runtime Domain gRPC 服务
- `saki-dispatcher`
  - 调度与编排推进
  - executor 注册、心跳、派发、回收
  - runtime/admin gRPC 控制入口
- `saki-executor`
  - 主动连接 dispatcher
  - 执行训练/评分/预测/评估 task
  - 上报事件、指标、候选、制品
- `saki-web`
  - React 前端工作台
  - 面向数据、标注、项目、Runtime、系统管理

### 2.2 插件与协议

- `saki-plugin-sdk`：插件公共契约（当前主版本 `4.x`）
- `saki-plugins/*`：插件实现（demo/yolo/oriented-rcnn）
- `proto/`：跨服务 gRPC 协议定义
- `scripts/gen_grpc.sh`：统一代码生成脚本

## 3. 仓库结构

```text
saki/
├── saki-api/
├── saki-dispatcher/
├── saki-executor/
├── saki-web/
├── saki-plugin-sdk/
├── saki-plugins/
├── proto/
├── scripts/
├── docs/
├── docker-compose.yml
├── env.example
└── deploy.sh
```

## 4. 文档入口

- 总索引：`docs/README.md`
- Runtime 生效语义：`docs/runtime-task-主干最终语义-v4.md`
- Runtime 维护 SQL：`docs/runtime-result-materialization-maintenance.sql`
- 部署指南：`DEPLOYMENT.md`
- 各子模块：子目录 `README.md`

## 5. 快速开始

## 5.1 Docker Compose（推荐）

1. 准备环境变量

```bash
cp env.example .env
```

2. 启动核心服务（API + Dispatcher + Web + Postgres + Redis + MinIO）

```bash
docker compose --profile minio up -d --build
```

3. 需要执行器时，增加 profile

```bash
docker compose --profile minio --profile saki-executor up -d --build
```

4. 查看状态与日志

```bash
docker compose ps
docker compose logs -f saki-api saki-dispatcher saki-web
```

## 5.2 本地开发

建议环境：

- Python `3.11+`
- `uv`
- Node.js `18+`
- Go `1.24+`
- PostgreSQL
- Redis

启动顺序建议：

1. API

```bash
cd saki-api
uv sync
make run
```

2. Dispatcher

```bash
cd saki-dispatcher
make run
```

3. Executor

```bash
cd saki-executor
make sync
make run
```

4. Web

```bash
cd saki-web
npm install
npm run dev
```

## 6. 常用开发命令

- 生成 gRPC stub：`bash scripts/gen_grpc.sh`
- 同步 schema + sqlc：`bash scripts/sync_schema.sh`
- Dispatcher 测试：`cd saki-dispatcher && make test`
- Web 构建：`cd saki-web && npm run build`

## 7. 关键环境变量（跨服务）

- API
  - `DATABASE_URL`
  - `MINIO_*`
  - `REDIS_URL`
  - `INTERNAL_TOKEN`
  - `RUNTIME_DOMAIN_GRPC_BIND`
- Dispatcher
  - `DATABASE_URL`
  - `RUNTIME_GRPC_BIND`
  - `ADMIN_GRPC_BIND`
  - `RUNTIME_DOMAIN_TARGET`
  - `INTERNAL_TOKEN`
- Executor
  - `API_GRPC_TARGET`
  - `EXECUTOR_ID`
  - `PLUGINS_DIR`
  - `RUNS_DIR`
  - `CACHE_DIR`
- Web
  - `VITE_API_BASE_URL`
  - 默认回退：`http://localhost:8000/api/v1`

## 8. Runtime 契约（必须对齐）

1. 业务真相源是 `saki-api`，执行器不直接写业务库。
2. 派发主键是 `task_id`，而非旧 `step_id` 语义。
3. `prediction` 是独立资源，不再沿用历史 `PredictionSet` 名称。
4. 文档、接口、日志字段必须与当前 task 主干语义一致。

## 9. 常见问题

1. Web 登录后 401
- 检查 Token 是否失效，系统时间是否漂移。

2. Executor 无法连接 dispatcher
- 检查 `API_GRPC_TARGET` 与 dispatcher `RUNTIME_GRPC_BIND`。
- 检查 `INTERNAL_TOKEN` 是否一致。

3. Dispatcher 不推进任务
- 检查 `DATABASE_URL`。
- 检查 `RUNTIME_DOMAIN_TARGET` 到 API runtime-domain 端口可达。

4. 构建和运行命令对不上
- 以各模块 `Makefile` / `package.json` / `pyproject.toml` 为准，不要使用历史文档命令。

## 10. 贡献与文档维护

1. 修改 Runtime 语义前，先更新主干语义文档再改代码。
2. 新增运行时文档需同步登记到 `docs/README.md`。
3. 不允许重新引入已移除的历史方案文档引用。
