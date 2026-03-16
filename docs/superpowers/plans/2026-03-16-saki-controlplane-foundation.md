# Saki Controlplane Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `saki-controlplane` 的最小可运行骨架，包括目录结构、代码生成、配置、日志、数据库基础设施与基础 CI。

**Architecture:** 先创建新的 Go controlplane 子项目，不迁业务逻辑。第一阶段只做“骨架正确”，包括 `public-api`、`runtime` 两个入口、`ogen/connect-go/sqlc/goose` 流水线、统一配置与日志门面。所有后续模块都基于这一基础设施增量实现。

**Tech Stack:** Go, `ogen`, `connect-go`, `buf`, `pgx/v5`, `sqlc`, `goose`, `caarlos0/env`, `slog`, OpenTelemetry

---

## Chunk 1: Repository Skeleton And Tooling

### Task 1: Create the new controlplane project skeleton

**Files:**
- Create: `saki-controlplane/go.mod`
- Create: `saki-controlplane/Makefile`
- Create: `saki-controlplane/cmd/public-api/main.go`
- Create: `saki-controlplane/cmd/runtime/main.go`
- Create: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Create: `saki-controlplane/internal/app/config/config.go`
- Create: `saki-controlplane/internal/app/observe/logger.go`
- Test: `saki-controlplane/internal/app/config/config_test.go`

- [ ] **Step 1: Write the failing config test**

```go
func TestLoadConfigDefaults(t *testing.T) {
    cfg, err := Load()
    if err != nil {
        t.Fatal(err)
    }
    if cfg.PublicAPIBind == "" || cfg.RuntimeBind == "" {
        t.Fatal("default binds must be set")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd saki-controlplane && go test ./internal/app/config -run TestLoadConfigDefaults -v`
Expected: FAIL with missing package or undefined `Load`

- [ ] **Step 3: Create the module and minimal config/bootstrap implementation**

```go
type Config struct {
    PublicAPIBind string `env:"PUBLIC_API_BIND" envDefault:":8080"`
    RuntimeBind   string `env:"RUNTIME_BIND" envDefault:":8081"`
    LogLevel      string `env:"LOG_LEVEL" envDefault:"INFO"`
}
```

- [ ] **Step 4: Add `main.go` entrypoints that call bootstrap and start an HTTP server**

Run: `cd saki-controlplane && go test ./...`
Expected: PASS for config tests and buildable stubs

- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/go.mod saki-controlplane/Makefile saki-controlplane/cmd saki-controlplane/internal/app
git commit -m "feat(controlplane): add foundation skeleton"
```

### Task 2: Add contract generation toolchain

**Files:**
- Create: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/api/proto/runtime/v1/agent_control.proto`
- Create: `saki-controlplane/api/proto/runtime/v1/agent_events.proto`
- Create: `saki-controlplane/api/proto/runtime/v1/artifact.proto`
- Create: `saki-controlplane/api/proto/worker/v1/worker.proto`
- Create: `saki-controlplane/buf.yaml`
- Create: `saki-controlplane/buf.gen.yaml`
- Create: `saki-controlplane/db/sqlc.yaml`
- Modify: `saki-controlplane/Makefile`
- Test: `saki-controlplane/internal/gen/.gitkeep`

- [ ] **Step 1: Write failing toolchain smoke checks**

```bash
cd saki-controlplane
make gen-openapi
make gen-proto
make gen-sqlc
```

Expected: FAIL because config files and specs do not exist

- [ ] **Step 2: Add minimal OpenAPI spec with `/healthz` and `/projects`**

```yaml
paths:
  /healthz:
    get:
      operationId: healthz
      responses:
        "200":
          description: ok
```

- [ ] **Step 3: Add minimal runtime/worker proto contracts**

```proto
service AgentControl {
  rpc Register(RegisterRequest) returns (RegisterResponse);
}
```

- [ ] **Step 4: Add `buf`, `ogen`, and `sqlc` generation targets**

Run: `cd saki-controlplane && make gen-openapi gen-proto gen-sqlc`
Expected: PASS and generated code under `internal/gen`

- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/api saki-controlplane/buf*.yaml saki-controlplane/db/sqlc.yaml saki-controlplane/Makefile saki-controlplane/internal/gen
git commit -m "build(controlplane): add code generation pipeline"
```

## Chunk 2: Database, Logging, And CI Baseline

### Task 3: Add database migrations and sqlc wiring

**Files:**
- Create: `saki-controlplane/db/migrations/000001_init_extensions.sql`
- Create: `saki-controlplane/db/migrations/000010_access_tables.sql`
- Create: `saki-controlplane/db/migrations/000020_project_tables.sql`
- Create: `saki-controlplane/db/migrations/000030_runtime_tables.sql`
- Create: `saki-controlplane/db/queries/project/create_project.sql`
- Create: `saki-controlplane/internal/app/db/pool.go`
- Create: `saki-controlplane/internal/app/db/tx.go`
- Create: `saki-controlplane/internal/modules/project/repo/project_repo.go`
- Test: `saki-controlplane/internal/modules/project/repo/project_repo_test.go`

- [ ] **Step 1: Write a failing repository integration test**

```go
func TestProjectRepoCreateProject(t *testing.T) {
    // start postgres testcontainer, run goose migrations, call repo.CreateProject
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd saki-controlplane && go test ./internal/modules/project/repo -run TestProjectRepoCreateProject -v`
Expected: FAIL because migrations/query/repo do not exist

- [ ] **Step 3: Add the first migrations and query files**

```sql
-- name: CreateProject :one
insert into project (id, name)
values (gen_random_uuid(), $1)
returning id, name;
```

- [ ] **Step 4: Add `pgx` pool wiring, `sqlc` generation, and repo adapter**

Run: `cd saki-controlplane && make gen-sqlc && go test ./internal/modules/project/repo -run TestProjectRepoCreateProject -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/db saki-controlplane/internal/app/db saki-controlplane/internal/modules/project/repo
git commit -m "feat(controlplane): add database foundation"
```

### Task 4: Add logging, observability, and CI baseline

**Files:**
- Create: `saki-controlplane/internal/app/observe/otel.go`
- Create: `saki-controlplane/.github/workflows/controlplane-ci.yml`
- Modify: `saki-controlplane/internal/app/observe/logger.go`
- Modify: `saki-controlplane/Makefile`
- Test: `saki-controlplane/internal/app/observe/logger_test.go`

- [ ] **Step 1: Write the failing logger test**

```go
func TestNewLoggerIncludesStaticFields(t *testing.T) {
    // assert logger emits module and service fields
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd saki-controlplane && go test ./internal/app/observe -run TestNewLoggerIncludesStaticFields -v`
Expected: FAIL

- [ ] **Step 3: Implement `slog` JSON/text logger factory and OTEL bootstrap stubs**

```go
func NewLogger(service string, level slog.Leveler) *slog.Logger
```

- [ ] **Step 4: Add CI targets for `go test`, generation drift check, and `go vet`**

Run: `cd saki-controlplane && go test ./... && go vet ./...`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/internal/app/observe saki-controlplane/.github/workflows/controlplane-ci.yml saki-controlplane/Makefile
git commit -m "chore(controlplane): add logging and ci baseline"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-controlplane-foundation.md`. Ready to execute?
