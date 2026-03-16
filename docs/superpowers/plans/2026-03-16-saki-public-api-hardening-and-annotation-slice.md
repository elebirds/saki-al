# Saki Public API Hardening And Annotation Slice Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `public-api` 从演示骨架改造成真实控制面接口，并落地 `annotation` 的最小纵向闭环。

**Architecture:** 先做 `public-api` 去占位化：统一 bootstrap 装配、去掉 MemoryStore、接入真实 repo/DB 与 runtime 状态机。然后沿 `sample -> annotation -> mapping sidecar` 做最小纵向切片，保持强一致写路径，避免 import/export 提前污染边界。

**Tech Stack:** Go, `ogen`, `pgx/v5`, `sqlc`, `goose`, PostgreSQL, Python, `uv`

---

## Chunk 1: Public API 装配与 Project 落实

### Task 1: 统一 `public-api` bootstrap 装配并移除硬编码依赖

**Files:**
- Modify: `saki-controlplane/internal/app/config/config.go`
- Modify: `saki-controlplane/internal/app/config/config_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server_test.go`
- Modify: `saki-controlplane/internal/modules/access/apihttp/handlers_test.go`

- [ ] **Step 1: 为 bootstrap 装配写失败测试**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/app/config ./internal/modules/system/apihttp ./internal/modules/access/apihttp -v` 并确认失败**
- [ ] **Step 3: 在 `config.go` 增加 `DATABASE_DSN`、`AUTH_TOKEN_SECRET`、`AUTH_TOKEN_TTL` 等配置项**
- [ ] **Step 4: 将 `bootstrap.go` 改为创建 `pgxpool`、`Authenticator` 与各模块依赖，不再让 `server.go` 自己 `new` memory store**
- [ ] **Step 5: 将 `server.go` 改为接收依赖构造 `Server` 和 `http.Handler`**
- [ ] **Step 6: 重新运行上述测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/internal/app/config saki-controlplane/internal/app/bootstrap saki-controlplane/internal/modules/system/apihttp saki-controlplane/internal/modules/access/apihttp
git commit -m "refactor(public-api): wire bootstrap dependencies"
```

### Task 2: 将 `project` API 全量切到真实 repo/DB

**Files:**
- Modify: `saki-controlplane/db/migrations/000020_project_tables.sql`
- Modify: `saki-controlplane/db/queries/project/create_project.sql`
- Modify: `saki-controlplane/db/queries/project/list_projects.sql`
- Modify: `saki-controlplane/db/queries/project/get_project.sql`
- Modify: `saki-controlplane/internal/modules/project/repo/project_repo.go`
- Modify: `saki-controlplane/internal/modules/project/repo/project_repo_test.go`
- Modify: `saki-controlplane/internal/modules/project/app/create_project.go`
- Modify: `saki-controlplane/internal/modules/project/app/list_projects.go`
- Modify: `saki-controlplane/internal/modules/project/app/get_project.go`
- Modify: `saki-controlplane/internal/modules/project/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/project/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`

- [ ] **Step 1: 为 `project` repo 和 `project` API 补失败测试，覆盖真实 repo store 路径**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/project/repo ./internal/modules/project/apihttp -v` 并确认失败**
- [ ] **Step 3: 给 `project` 表补 `created_at`、`updated_at` 字段，并更新 SQL 查询**
- [ ] **Step 4: 调整 `ProjectRepo` 返回结构与 repo 测试**
- [ ] **Step 5: 删除 `project/app` 对 `MemoryStore` 的依赖路径，让 `server.go` 通过 `RepoStore` 装配**
- [ ] **Step 6: 重新运行 `project` repo/API 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/db/migrations/000020_project_tables.sql saki-controlplane/db/queries/project saki-controlplane/internal/modules/project saki-controlplane/internal/modules/system/apihttp/server.go
git commit -m "feat(project): back project api with repo store"
```

## Chunk 2: Runtime Admin 真实读模型与命令入口

### Task 3: 持久化 `runtime_executor` 读模型

**Files:**
- Modify: `saki-controlplane/db/migrations/000030_runtime_tables.sql`
- Create: `saki-controlplane/db/queries/runtime/executor.sql`
- Create: `saki-controlplane/internal/modules/runtime/repo/executor_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/register_executor.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/heartbeat_executor.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`

- [ ] **Step 1: 为 `runtime_executor` repo 与 register/heartbeat 持久化路径写失败测试**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/runtime/repo ./internal/modules/runtime/internalrpc -v` 并确认失败**
- [ ] **Step 3: 在 runtime migration 中新增 `runtime_executor` 表**
- [ ] **Step 4: 编写 `executor.sql` 并执行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make check-gen` 更新 `sqlc` 产物**
- [ ] **Step 5: 实现 `ExecutorRepo`，并让 `register_executor` / `heartbeat_executor` 写入 executor 读模型**
- [ ] **Step 6: 重新运行 repo/internalrpc 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/db/migrations/000030_runtime_tables.sql saki-controlplane/db/queries/runtime/executor.sql saki-controlplane/internal/modules/runtime/repo saki-controlplane/internal/modules/runtime/app/commands saki-controlplane/internal/modules/runtime/internalrpc
git commit -m "feat(runtime): persist executor admin read model"
```

### Task 4: 用真实 repo 替换 `runtime-admin` 的 `MemoryAdminStore`

**Files:**
- Modify: `saki-controlplane/db/queries/runtime/task.sql`
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/app/queries/admin_store.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/list_executors.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/issue_runtime_command.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/cancel_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`

- [ ] **Step 1: 为 `runtime-admin` 查询和 `cancel task` 命令写失败测试**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/runtime/apihttp ./internal/modules/runtime/app/commands -v` 并确认失败**
- [ ] **Step 3: 给 `runtime_task` SQL 补 `GetTask`、`CancelTask`、summary 聚合和 executor 列表查询**
- [ ] **Step 4: 新建 repo-backed `AdminStore` 实现，删除 `MemoryAdminStore` 在 `server.go` 中的装配**
- [ ] **Step 5: 新增 `cancel_task.go`，要求命令通过 `TaskStateMachine.CancelTask` 和 outbox 写入**
- [ ] **Step 6: 重新运行 runtime admin 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/db/queries/runtime/task.sql saki-controlplane/internal/modules/runtime/repo saki-controlplane/internal/modules/runtime/app/queries saki-controlplane/internal/modules/runtime/app/commands/cancel_task.go saki-controlplane/internal/modules/runtime/apihttp saki-controlplane/internal/modules/system/apihttp/server.go
git commit -m "feat(runtime): back runtime admin api with repos"
```

## Chunk 3: Annotation 最小数据模型与 API

### Task 5: 落地 `sample` / `annotation` 最小 schema 与 repo

**Files:**
- Create: `saki-controlplane/db/migrations/000040_annotation_tables.sql`
- Create: `saki-controlplane/db/queries/annotation/sample.sql`
- Create: `saki-controlplane/db/queries/annotation/annotation.sql`
- Create: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`
- Create: `saki-controlplane/internal/modules/annotation/repo/annotation_repo.go`
- Create: `saki-controlplane/internal/modules/annotation/repo/repo_test.go`

- [ ] **Step 1: 为 `sample` / `annotation` repo 写失败测试，覆盖创建 annotation 与按 sample 读取**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/annotation/repo -v` 并确认失败**
- [ ] **Step 3: 新增 `sample`、`annotation` 表迁移，并保留 `sample.meta jsonb` 作为 lookup metadata 容器**
- [ ] **Step 4: 新增 annotation SQL 文件并执行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make check-gen` 更新 `sqlc`**
- [ ] **Step 5: 实现 `SampleRepo`、`AnnotationRepo` 与 repo 测试**
- [ ] **Step 6: 重新运行 annotation repo 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/db/migrations/000040_annotation_tables.sql saki-controlplane/db/queries/annotation saki-controlplane/internal/modules/annotation/repo
git commit -m "feat(annotation): add annotation schema and repo"
```

### Task 6: 实现 `annotation` create/list API，不接 sidecar

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/annotation/domain/annotation.go`
- Create: `saki-controlplane/internal/modules/annotation/app/create_annotation.go`
- Create: `saki-controlplane/internal/modules/annotation/app/list_annotations.go`
- Create: `saki-controlplane/internal/modules/annotation/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/annotation/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`

- [ ] **Step 1: 为 `POST /samples/{sample_id}/annotations` 和 `GET /samples/{sample_id}/annotations` 写失败测试**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make gen-openapi && PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/annotation/apihttp -v` 并确认失败**
- [ ] **Step 3: 在 `public-api.yaml` 中新增 annotation create/list 路径、请求体和响应模型**
- [ ] **Step 4: 在 `domain` 与 `app` 层实现最小 geometry normalize、create/list use case，先只写源 annotation**
- [ ] **Step 5: 在 `apihttp` 层接到 annotation use case，并让 `server.go` 装配新 handler**
- [ ] **Step 6: 重新运行 `make gen-openapi` 与 annotation API 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/annotation/domain saki-controlplane/internal/modules/annotation/app saki-controlplane/internal/modules/annotation/apihttp saki-controlplane/internal/modules/system/apihttp/server.go
git commit -m "feat(annotation): add annotation create and list api"
```

## Chunk 4: FEDO Mapping Sidecar 接入与整体验证

### Task 7: 将 FEDO mapping sidecar 接入 annotation create 流

**Files:**
- Modify: `saki-controlplane/internal/modules/annotation/app/create_annotation.go`
- Modify: `saki-controlplane/internal/modules/annotation/app/mapping/client.go`
- Modify: `saki-controlplane/internal/modules/annotation/app/mapping/client_test.go`
- Create: `saki-controlplane/internal/modules/annotation/app/create_annotation_test.go`
- Modify: `saki-mapping-engine/src/saki_mapping_engine/fedo_mapper.py`
- Modify: `saki-mapping-engine/tests/test_fedo_mapper.py`

- [ ] **Step 1: 为 annotation create 用例写失败测试，覆盖 sample 为 FEDO 时同时生成 source/target annotation**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/annotation/app ./internal/modules/annotation/app/mapping -v` 并确认失败**
- [ ] **Step 3: 在 `create_annotation.go` 中读取 `sample.meta` 的 lookup/view 信息，按需调用 `mapping.Client`**
- [ ] **Step 4: 保持强一致语义：sidecar 失败则整个 create 失败，并补足对应测试**
- [ ] **Step 5: 运行 `uv run --project saki-mapping-engine --extra dev pytest tests/test_fedo_mapper.py -v` 并确认 Python 侧映射测试仍通过**
- [ ] **Step 6: 重新运行 annotation app/mapping 测试并确认通过**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/internal/modules/annotation/app saki-controlplane/internal/modules/annotation/app/mapping saki-mapping-engine/src/saki_mapping_engine/fedo_mapper.py saki-mapping-engine/tests/test_fedo_mapper.py
git commit -m "feat(annotation): wire FEDO mapping sidecar into create flow"
```

### Task 8: 做最终回归验证并更新执行基线

**Files:**
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`
- Modify: `saki-controlplane/Makefile`
- Modify: `saki-controlplane/.github/workflows/controlplane-ci.yml`

- [ ] **Step 1: 为 annotation create/list 新增 smoke 覆盖点，并让 smoke 测试先失败**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make smoke-public-api` 并确认失败**
- [ ] **Step 3: 将 annotation 路径加入 smoke 测试基线，必要时在 Makefile 中补文档化命令**
- [ ] **Step 4: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./... && PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go vet ./...` 于 `saki-controlplane`**
- [ ] **Step 5: 运行 `uv run --extra dev pytest tests/test_worker_runtime.py -v` 于 `saki-plugin-sdk`**
- [ ] **Step 6: 运行 `uv run --extra dev pytest tests/test_fedo_mapper.py -v` 于 `saki-mapping-engine`**
- [ ] **Step 7: Commit**

```bash
git add saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go saki-controlplane/Makefile saki-controlplane/.github/workflows/controlplane-ci.yml
git commit -m "chore(public-api): extend smoke coverage for annotation"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-public-api-hardening-and-annotation-slice.md`. Ready to execute?
