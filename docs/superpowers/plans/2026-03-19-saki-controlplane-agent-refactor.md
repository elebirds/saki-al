# Saki Controlplane / Agent Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把旧 `saki-api runtime bridge + dispatcher + executor` 收敛为 `public-api + runtime(controlplane) + agent`，以 `DB/command-first + pull-first` 为主线完成动态 agent 路由、agent 并发控制、恢复逻辑和可选 relay 扩展。

**Architecture:** `saki-controlplane` 继续作为单代码库、多 role 的 bounded context；系统真相落在 Postgres，不落在长连接或 broker。默认传输模式是 `pull`，`direct` 仅用于开发和过渡，`relay` 放在最后一个 gated chunk 中实现为可选 delivery adapter，而不是新的系统真相中心。

**Tech Stack:** Go, connect-go, buf, pgx/v5, sqlc, goose, ogen, testcontainers-go, PostgreSQL

---

## Frozen Decisions

- 迁移期间保留模块目录 `saki-controlplane/internal/modules/runtime`，不做大规模目录改名；先改语义和边界，再考虑目录清理。
- 代码级命名统一从 `executor` 收敛为 `agent`。
- 持久化命名冻结为：
  - `runtime_task` 保留。
  - `runtime_lease` 保留。
  - `runtime_executor` 迁移为 `agent`。
  - `runtime_outbox` 迁移为 `agent_command`。
  - 新增 `task_assignment`。
  - 可选 `agent_session` 仅给 relay 使用。
- `public-api` 不直接接触任何 agent transport。
- `runtime` 内部 role 固定为 `ingress`、`scheduler`、`delivery`、`recovery`，可选 `relay`。
- 并发真相在 agent 本地 slot，不在 controlplane 维护隐藏队列。
- 默认 transport 顺序：`pull` > `direct` > `relay(optional)`。

## Phase Gates

1. **Gate A:** runtime 能按 role 独立启停，但行为不变。
2. **Gate B:** 动态 `agent` registry + `task_assignment` + `agent_command` 跑通，静态 `RUNTIME_SCHEDULER_TARGET_AGENT` 和静态 `RUNTIME_AGENT_CONTROL_BASE_URL` 退出主路径。
3. **Gate C:** agent slot 并发和 `pull` 最小闭环通过端到端测试。
4. **Gate D:** recovery 能处理失联、未确认 assign、cancel 超时。
5. **Gate E:** `public-api`、compose、README、env 全部切到 controlplane/agent 语义。
6. **Gate F (Optional):** relay 独立部署并接入 delivery adapter。

## Chunk 1: Freeze Roles And Vocabulary

### Task 1: 先把 `runtime` 进程拆成可独立启停的 role 壳子

**Files:**
- Modify: `saki-controlplane/internal/app/config/config.go`
- Modify: `saki-controlplane/internal/app/config/config_test.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/process.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/role_set.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/ingress_role.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/scheduler_role.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/delivery_role.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/recovery_role.go`
- Test: `saki-controlplane/internal/app/config/config_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`

- [ ] **Step 1: 写失败测试，冻结 role 配置面**

```go
func TestLoadRuntimeConfig_DefaultRoles(t *testing.T) {}
func TestRunner_OnlyStartsEnabledRoles(t *testing.T) {}
```

明确配置面：

```go
type RuntimeRole string

const (
    RuntimeRoleIngress   RuntimeRole = "ingress"
    RuntimeRoleScheduler RuntimeRole = "scheduler"
    RuntimeRoleDelivery  RuntimeRole = "delivery"
    RuntimeRoleRecovery  RuntimeRole = "recovery"
)
```

- [ ] **Step 2: 运行配置与 runner 单测，确认当前实现还只有单体 runner**

Run: `cd saki-controlplane && go test ./internal/app/config ./internal/modules/runtime/app/runtime -run 'TestLoadRuntimeConfig|TestRunner' -v`

Expected: FAIL，原因是当前 `NewRuntime` 仍把 HTTP server、scheduler 和 outbox worker 固定绑在一个进程里。

- [ ] **Step 3: 加入 role-set 配置并拆出 role 壳子**

配置要求：

```go
type Config struct {
    RuntimeBind  string   `env:"RUNTIME_BIND" envDefault:":8081"`
    RuntimeRoles []string `env:"RUNTIME_ROLES" envDefault:"ingress,scheduler,delivery,recovery"`
}
```

实现要求：

```go
type Process struct {
    Server     *http.Server
    Background []loopRunner
}
```

`ingress` 只挂 RPC server；`scheduler`、`delivery`、`recovery` 只注入各自 loop；禁用 role 时不启动对应组件。

- [ ] **Step 4: 重新运行配置与 runner 测试**

Run: `cd saki-controlplane && go test ./internal/app/config ./internal/modules/runtime/app/runtime -run 'TestLoadRuntimeConfig|TestRunner' -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/app/config/config.go \
  saki-controlplane/internal/app/config/config_test.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go \
  saki-controlplane/internal/modules/runtime/app/runtime/process.go \
  saki-controlplane/internal/modules/runtime/app/runtime/role_set.go \
  saki-controlplane/internal/modules/runtime/app/runtime/ingress_role.go \
  saki-controlplane/internal/modules/runtime/app/runtime/scheduler_role.go \
  saki-controlplane/internal/modules/runtime/app/runtime/delivery_role.go \
  saki-controlplane/internal/modules/runtime/app/runtime/recovery_role.go
git commit -m "refactor(runtime): split runtime process into roles"
```

### Task 2: 把代码级 `executor` 词汇整体收敛为 `agent`

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/register_executor.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/heartbeat_executor.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/list_executors.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Modify: `saki-agent/internal/app/connect/client.go`
- Modify: `saki-agent/internal/app/connect/client_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Test: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`
- Test: `saki-agent/internal/app/connect/client_test.go`

- [ ] **Step 1: 写失败测试，锁定新语义必须只出现 `agent`**

```go
func TestRegisterAgentRequestCarriesAgentIdentity(t *testing.T) {}
func TestListRuntimeAgentsQueryReturnsAgentVocabulary(t *testing.T) {}
```

- [ ] **Step 2: 运行相关单测，确认代码仍暴露 `Executor*` 类型名**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/apihttp -v`

Run: `cd saki-agent && go test ./internal/app/connect -v`

Expected: FAIL，原因是现有 handler/query/client 仍以 `ExecutorRecord`、`ExecutorRegistry`、`ListExecutorsQuery` 为主名词。

- [ ] **Step 3: 做机械改名，但暂不改数据库表名**

最小目标：

```go
type AgentRecord struct {
    ID              string
    Version         string
    Capabilities    []string
    TransportMode   string
    ControlBaseURL  string
    MaxConcurrency  int32
    RunningTaskIDs  []string
    LastSeenAt      time.Time
}
```

要求：

1. Go 类型、接口、query/usecase 全部切到 `Agent` 词汇。
2. 对外 HTTP/OpenAPI 文案改成 `agents`，数据库兼容层暂时允许内部 repo 仍指向旧表。
3. 暂不改模块目录名 `runtime`，避免把边界重构和目录重构绑死。

- [ ] **Step 4: 重新运行语义相关测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/apihttp -v`

Run: `cd saki-agent && go test ./internal/app/connect -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/app/commands/register_executor.go \
  saki-controlplane/internal/modules/runtime/app/commands/heartbeat_executor.go \
  saki-controlplane/internal/modules/runtime/app/queries/list_executors.go \
  saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go \
  saki-controlplane/internal/modules/runtime/apihttp/handlers.go \
  saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go \
  saki-agent/internal/app/connect/client.go \
  saki-agent/internal/app/connect/client_test.go
git commit -m "refactor(runtime): rename executor vocabulary to agent"
```

## Chunk 2: Move Truth Into Agent Registry And Commands

### Task 3: 新增 `agent`、`task_assignment`、`agent_command` 持久层，并保留迁移窗口

**Files:**
- Create: `saki-controlplane/db/migrations/000072_agent_registry_and_command.sql`
- Create: `saki-controlplane/db/queries/runtime/agent.sql`
- Create: `saki-controlplane/db/queries/runtime/task_assignment.sql`
- Create: `saki-controlplane/db/queries/runtime/agent_command.sql`
- Modify: `saki-controlplane/db/sqlc.yaml`
- Modify: `saki-controlplane/internal/gen/sqlc`
- Create: `saki-controlplane/internal/modules/runtime/repo/agent_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/task_assignment_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/agent_command_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`
- Modify: `shared/db/schema.sql`
- Modify: `scripts/sync_schema.sh`
- Test: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`

- [ ] **Step 1: 写失败的 repo 集成测试，冻结新表的最小语义**

```go
func TestAgentRepo_RegisterHeartbeatAndList(t *testing.T) {}
func TestTaskAssignmentRepo_CreateAssignment(t *testing.T) {}
func TestAgentCommandRepo_AppendClaimAckAndRetry(t *testing.T) {}
```

至少验证：

1. `agent` 记录 `transport_mode`、`control_base_url`、`max_concurrency`、`running_task_ids`。
2. `task_assignment` 一次 assign 生成唯一 `execution_id`。
3. `agent_command` 支持 pending、claim、ack、retry、expire。

- [ ] **Step 2: 运行 repo 测试，确认当前 schema 还不具备这些对象**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/repo -run 'TestAgentRepo|TestTaskAssignmentRepo|TestAgentCommandRepo' -v`

Expected: FAIL，原因是当前只有 `runtime_executor` 和 `runtime_outbox`，缺少 assignment 与 command 真相对象。

- [ ] **Step 3: 新增 additive migration，不做 destructive cleanup**

迁移冻结为：

```sql
create type agent_transport_mode as enum ('direct', 'pull', 'relay');
create type agent_command_type as enum ('assign', 'cancel');
create type agent_command_status as enum ('pending', 'claimed', 'acked', 'finished', 'failed', 'expired');

create table agent (
    id text primary key,
    version text not null,
    capabilities text[] not null default '{}',
    transport_mode agent_transport_mode not null,
    control_base_url text not null default '',
    max_concurrency integer not null default 1,
    running_task_ids text[] not null default '{}',
    status text not null default 'online',
    last_seen_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
```

```sql
create table task_assignment (
    id bigserial primary key,
    task_id uuid not null references runtime_task(id) on delete cascade,
    attempt integer not null,
    agent_id text not null references agent(id),
    execution_id text not null,
    status text not null,
    assigned_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    cancel_requested_at timestamptz,
    terminal_reason text,
    unique (task_id, attempt),
    unique (execution_id)
);
```

```sql
create table agent_command (
    id bigserial primary key,
    command_id uuid not null unique,
    agent_id text not null references agent(id),
    task_id uuid references runtime_task(id) on delete cascade,
    assignment_id bigint references task_assignment(id) on delete cascade,
    command_type agent_command_type not null,
    transport_mode agent_transport_mode not null,
    payload jsonb not null,
    status agent_command_status not null default 'pending',
    claim_token uuid,
    available_at timestamptz not null default now(),
    acked_at timestamptz,
    finished_at timestamptz,
    expire_at timestamptz,
    attempt_count integer not null default 0,
    last_error text,
    created_at timestamptz not null default now()
);
```

兼容策略：

1. 本任务不删除 `runtime_executor`、`runtime_outbox`。
2. 若需要历史兼容，先从 `runtime_executor` 单次 backfill 到 `agent`。
3. 后续代码全部切到新表，再做旧表下线。

- [ ] **Step 4: 生成 sqlc 并实现 repo**

要求：

1. `AgentRepo.UpsertHeartbeat()` 一次写入版本、能力、transport、容量和运行中 task。
2. `TaskAssignmentRepo.Assign()` 在事务内生成 assignment。
3. `AgentCommandRepo` 暴露 `AppendAssign`、`AppendCancel`、`ClaimForPush`、`ClaimForPull`、`Ack`、`MarkFinished`、`MarkRetry`。

- [ ] **Step 5: 重新生成代码并跑 repo 测试**

Run: `cd saki-controlplane && make gen-sqlc && go test ./internal/modules/runtime/repo -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  saki-controlplane/db/migrations/000072_agent_registry_and_command.sql \
  saki-controlplane/db/queries/runtime/agent.sql \
  saki-controlplane/db/queries/runtime/task_assignment.sql \
  saki-controlplane/db/queries/runtime/agent_command.sql \
  saki-controlplane/db/sqlc.yaml \
  saki-controlplane/internal/gen/sqlc \
  saki-controlplane/internal/modules/runtime/repo/agent_repo.go \
  saki-controlplane/internal/modules/runtime/repo/task_assignment_repo.go \
  saki-controlplane/internal/modules/runtime/repo/agent_command_repo.go \
  saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go \
  shared/db/schema.sql \
  scripts/sync_schema.sh
git commit -m "feat(runtime): add agent registry assignment and command persistence"
```

### Task 4: 扩展 ingress 协议，让 agent 注册/心跳携带真实调度信息

**Files:**
- Modify: `saki-controlplane/api/proto/runtime/v1/agent_ingress.proto`
- Modify: `saki-agent/api/proto/runtime/v1/agent_ingress.proto`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`
- Modify: `saki-agent/internal/app/connect/runtime_contract_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/register_agent.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/heartbeat_agent.go`
- Modify: `saki-agent/internal/app/connect/client.go`
- Modify: `saki-agent/internal/app/connect/client_test.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-agent/internal/app/config/config.go`
- Modify: `saki-agent/internal/app/config/config_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Test: `saki-agent/internal/app/connect/client_test.go`
- Test: `saki-agent/internal/app/bootstrap/bootstrap_test.go`

- [ ] **Step 1: 写失败合同测试，锁定 register/heartbeat 载荷**

```proto
message RegisterRequest {
  string agent_id = 1;
  string version = 2;
  repeated string capabilities = 3;
  string transport_mode = 4;
  string control_base_url = 5;
  int32 max_concurrency = 6;
}

message HeartbeatRequest {
  string agent_id = 1;
  string agent_version = 2;
  repeated string running_task_ids = 3;
  int32 max_concurrency = 4;
  int64 sent_at_unix_ms = 5;
}
```

- [ ] **Step 2: 运行 proto/client/server 测试，确认现有 contract 信息不足**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc -v`

Run: `cd saki-agent && make gen-proto && go test ./internal/app/connect ./internal/app/bootstrap ./internal/app/config -v`

Expected: FAIL，原因是现有 register/heartbeat 不携带 transport 与容量信息。

- [ ] **Step 3: 增量修改 proto 与 command handler**

实现要求：

```go
type RegisterAgentCommand struct {
    AgentID         string
    Version         string
    Capabilities    []string
    TransportMode   string
    ControlBaseURL  string
    MaxConcurrency  int32
    SeenAt          time.Time
}

type HeartbeatAgentCommand struct {
    AgentID         string
    Version         string
    RunningTaskIDs  []string
    MaxConcurrency  int32
    SeenAt          time.Time
}
```

规则：

1. `direct` 模式下 `control_base_url` 必须非空。
2. `pull` 和 `relay` 模式允许 `control_base_url` 为空。
3. `max_concurrency <= 0` 时服务端归一化为 `1`。

- [ ] **Step 4: 重新生成 proto 并跑 server/client/bootstrap 测试**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc -v`

Run: `cd saki-agent && make gen-proto && go test ./internal/app/connect ./internal/app/bootstrap ./internal/app/config -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/proto/runtime/v1/agent_ingress.proto \
  saki-agent/api/proto/runtime/v1/agent_ingress.proto \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go \
  saki-agent/internal/app/connect/runtime_contract_test.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go \
  saki-controlplane/internal/modules/runtime/app/commands/register_agent.go \
  saki-controlplane/internal/modules/runtime/app/commands/heartbeat_agent.go \
  saki-agent/internal/app/connect/client.go \
  saki-agent/internal/app/connect/client_test.go \
  saki-agent/internal/app/bootstrap/bootstrap.go \
  saki-agent/internal/app/bootstrap/bootstrap_test.go \
  saki-agent/internal/app/config/config.go \
  saki-agent/internal/app/config/config_test.go \
  saki-controlplane/internal/gen/proto \
  saki-agent/internal/gen/runtime
git commit -m "feat(runtime): enrich agent ingress registration and heartbeat"
```

## Chunk 3: Dynamic Scheduling And Delivery

### Task 5: 用 `agent` registry + `task_assignment` 重写调度主链路

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/tick.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/tick_test.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/agent_selector.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/agent_selector_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Modify: `saki-controlplane/db/queries/runtime/task.sql`
- Test: `saki-controlplane/internal/modules/runtime/app/scheduler/...`
- Test: `saki-controlplane/internal/modules/runtime/app/commands/...`

- [ ] **Step 1: 写失败测试，锁定“调度只负责选择和落库”**

```go
func TestDispatchScan_SelectsBestAgentAndCreatesAssignment(t *testing.T) {}
func TestAssignTaskHandler_AppendsAssignCommandInSameTx(t *testing.T) {}
```

筛选规则最小化为：

1. 只选择 `status=online`。
2. `capabilities` 必须满足任务声明。
3. `len(running_task_ids) < max_concurrency`。
4. 同容量下按 `last_seen_at desc, id asc` 选。

- [ ] **Step 2: 运行 scheduler/command 测试，确认当前实现仍依赖静态 target agent**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/scheduler ./internal/modules/runtime/app/commands -v`

Expected: FAIL，原因是当前 `SchedulerTargetAgent` 仍是唯一 agent 来源，且 assign 逻辑没有 assignment 真相。

- [ ] **Step 3: 重写 assign 事务**

事务要求：

1. claim 一个 `pending` task。
2. 选择目标 agent。
3. 写入 `task_assignment(status='assigned')`。
4. 更新 `runtime_task.assigned_agent_id/current_execution_id/attempt/status`。
5. 追加 `agent_command(command_type='assign', transport_mode=agent.transport_mode)`。

事务输出：

```go
type AssignResult struct {
    TaskID       uuid.UUID
    AssignmentID int64
    ExecutionID  string
    AgentID      string
}
```

- [ ] **Step 4: 重新运行 scheduler/command 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/scheduler ./internal/modules/runtime/app/commands -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan_test.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/tick.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/tick_test.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/agent_selector.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/agent_selector_test.go \
  saki-controlplane/internal/modules/runtime/repo/task_repo.go \
  saki-controlplane/db/queries/runtime/task.sql
git commit -m "feat(runtime): schedule tasks through dynamic agent registry"
```

### Task 6: 把 delivery 改成 transport adapter，不再用静态 `base URL`

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/runner.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/agent_control_client.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/agent_control_client_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/worker.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/stop_effect.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/stop_effect_test.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/transport_registry.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/direct_transport.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/pull_transport.go`
- Test: `saki-controlplane/internal/modules/runtime/effects/...`
- Test: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`

- [ ] **Step 1: 写失败测试，锁定 per-agent transport 选择**

```go
func TestDispatchEffect_UsesDirectTransportPerAgent(t *testing.T) {}
func TestDispatchEffect_PullModeLeavesCommandForAgentClaim(t *testing.T) {}
func TestStopEffect_UsesAgentCommandRepoNotStaticBaseURL(t *testing.T) {}
```

- [ ] **Step 2: 运行 delivery/effects 测试，确认当前代码仍用单一 `AgentControlBaseURL`**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/effects ./internal/modules/runtime/app/runtime -v`

Expected: FAIL，原因是当前 transport 创建仍依赖全局 `AgentControlBaseURL`。

- [ ] **Step 3: 引入 transport registry**

接口冻结为：

```go
type CommandTransport interface {
    Mode() string
    DispatchAssign(ctx context.Context, cmd AgentCommand) error
    DispatchCancel(ctx context.Context, cmd AgentCommand) error
}
```

规则：

1. `direct`：delivery worker 主动推送，并在成功后 `Ack + Finish`。
2. `pull`：delivery worker 不主动推送，只保证命令处于 `pending` 可领取状态。
3. `relay`：先返回 `ErrTransportNotConfigured`，待最后一个 chunk 接入。

- [ ] **Step 4: 重新运行 delivery/effects 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/effects ./internal/modules/runtime/app/runtime -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/app/runtime/runner.go \
  saki-controlplane/internal/modules/runtime/app/runtime/agent_control_client.go \
  saki-controlplane/internal/modules/runtime/app/runtime/agent_control_client_test.go \
  saki-controlplane/internal/modules/runtime/effects/worker.go \
  saki-controlplane/internal/modules/runtime/effects/dispatch_effect.go \
  saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go \
  saki-controlplane/internal/modules/runtime/effects/stop_effect.go \
  saki-controlplane/internal/modules/runtime/effects/stop_effect_test.go \
  saki-controlplane/internal/modules/runtime/effects/transport_registry.go \
  saki-controlplane/internal/modules/runtime/effects/direct_transport.go \
  saki-controlplane/internal/modules/runtime/effects/pull_transport.go
git commit -m "refactor(runtime): make delivery transport per-agent and pluggable"
```

## Chunk 4: Agent Capacity And Pull Closure

### Task 7: 把 agent 从单任务模型改成 slot-based 并发模型

**Files:**
- Modify: `saki-agent/internal/app/config/config.go`
- Modify: `saki-agent/internal/app/config/config_test.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-agent/internal/app/runtime/service.go`
- Modify: `saki-agent/internal/app/runtime/service_test.go`
- Modify: `saki-agent/internal/app/runtime/control_server.go`
- Modify: `saki-agent/internal/app/runtime/control_server_test.go`
- Create: `saki-agent/internal/app/runtime/slot_manager.go`
- Create: `saki-agent/internal/app/runtime/slot_manager_test.go`
- Modify: `saki-agent/internal/plugins/launcher/launcher_test.go`
- Test: `saki-agent/internal/app/runtime/...`

- [ ] **Step 1: 写失败测试，冻结 slot admission 语义**

```go
func TestService_AssignTaskUsesNextFreeSlot(t *testing.T) {}
func TestService_AssignTaskRejectsWhenAllSlotsBusy(t *testing.T) {}
func TestService_StopTaskCancelsMatchingExecutionOnly(t *testing.T) {}
```

- [ ] **Step 2: 运行 agent runtime 测试，确认当前只支持单个 active execution**

Run: `cd saki-agent && go test ./internal/app/runtime -v`

Expected: FAIL，原因是当前 `Service` 只有 `current *activeExecution`。

- [ ] **Step 3: 引入 slot manager**

配置冻结为：

```go
type Config struct {
    RuntimeBaseURL         string
    AgentID                string
    AgentVersion           string
    AgentTransportMode     string
    AgentControlBind       string
    AgentMaxConcurrency    int
    AgentHeartbeatInterval time.Duration
}
```

运行时结构：

```go
type SlotManager struct {
    slots map[string]*activeExecution
    limit int
}
```

要求：

1. `AssignTask` 先做 admission，再异步启动。
2. `RunningTaskIDs()` 返回全部活跃 task。
3. 不做 agent 本地排队；满了就立即拒绝。

- [ ] **Step 4: 重新运行 agent runtime 测试**

Run: `cd saki-agent && go test ./internal/app/runtime -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-agent/internal/app/config/config.go \
  saki-agent/internal/app/config/config_test.go \
  saki-agent/internal/app/bootstrap/bootstrap.go \
  saki-agent/internal/app/bootstrap/bootstrap_test.go \
  saki-agent/internal/app/runtime/service.go \
  saki-agent/internal/app/runtime/service_test.go \
  saki-agent/internal/app/runtime/control_server.go \
  saki-agent/internal/app/runtime/control_server_test.go \
  saki-agent/internal/app/runtime/slot_manager.go \
  saki-agent/internal/app/runtime/slot_manager_test.go \
  saki-agent/internal/plugins/launcher/launcher_test.go
git commit -m "feat(agent): add slot based concurrency admission"
```

### Task 8: 增加 `pull` delivery 协议，并闭合 assign/cancel 端到端

**Files:**
- Create: `saki-controlplane/api/proto/runtime/v1/agent_delivery.proto`
- Create: `saki-agent/api/proto/runtime/v1/agent_delivery.proto`
- Modify: `saki-controlplane/buf.gen.yaml`
- Modify: `saki-agent/buf.gen.yaml`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/delivery_server.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/delivery_server_test.go`
- Create: `saki-agent/internal/app/connect/delivery_client.go`
- Create: `saki-agent/internal/app/connect/delivery_client_test.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap_test.go`
- Modify: `saki-agent/internal/app/connect/client.go`
- Modify: `saki-agent/cmd/agent/main.go`
- Modify: `saki-agent/cmd/agent/main_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go`
- Test: `saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go`
- Test: `saki-agent/internal/app/connect/...`

- [ ] **Step 1: 写失败合同测试，冻结 pull 协议**

```proto
service AgentDelivery {
  rpc PullCommands(PullCommandsRequest) returns (PullCommandsResponse);
  rpc AckCommand(AckCommandRequest) returns (AckCommandResponse);
}

message PullCommandsRequest {
  string agent_id = 1;
  int32 max_items = 2;
  int64 wait_timeout_ms = 3;
}
```

```proto
message PulledCommand {
  string command_id = 1;
  string command_type = 2;
  string task_id = 3;
  string execution_id = 4;
  bytes payload = 5;
  string delivery_token = 6;
}
```

- [ ] **Step 2: 运行 proto/client/e2e 测试，确认 pull 路径尚不存在**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/e2e -run 'TestAgentDelivery|TestRuntimeAgentClosure' -v`

Run: `cd saki-agent && make gen-proto && go test ./internal/app/connect ./cmd/agent -v`

Expected: FAIL，原因是 runtime 还没有 `AgentDelivery` server，agent 也没有 pull loop。

- [ ] **Step 3: 实现 runtime delivery server 与 agent pull loop**

语义要求：

1. `PullCommands` 只给指定 `agent_id` 返回当前可领取的 `pending` 命令。
2. 返回时把命令更新成 `claimed`，并生成 `delivery_token`。
3. `AckCommand` 用 `delivery_token` 把命令推进到 `acked` 或 `finished`。
4. `assign` 命令在 agent 接收后先 `Ack(received)`，然后执行。
5. `cancel` 命令在 agent 接收后先 `Ack(received)`，然后本地触发取消。

- [ ] **Step 4: 增加 agent 后台 pull loop**

伪代码：

```go
for ctx.Err() == nil {
    resp, err := delivery.PullCommands(ctx, agentID, 8, 25_000)
    if err != nil { backoff(); continue }
    for _, cmd := range resp.Commands {
        handle(cmd)
        _ = delivery.AckCommand(ctx, cmd.CommandId, cmd.DeliveryToken, "received")
    }
}
```

- [ ] **Step 5: 跑真实闭环测试**

Run: `cd saki-agent && go test ./...`

Run: `cd saki-controlplane && go test ./internal/modules/runtime/... -count=1`

Expected: PASS，新增至少覆盖：

1. `pull` 模式下 assign 能到达 agent 并成功完成。
2. `pull` 模式下 cancel 能到达 agent 并最终把 task 置为 `canceled`。

- [ ] **Step 6: Commit**

```bash
git add \
  saki-controlplane/api/proto/runtime/v1/agent_delivery.proto \
  saki-agent/api/proto/runtime/v1/agent_delivery.proto \
  saki-controlplane/buf.gen.yaml \
  saki-agent/buf.gen.yaml \
  saki-controlplane/internal/modules/runtime/internalrpc/delivery_server.go \
  saki-controlplane/internal/modules/runtime/internalrpc/delivery_server_test.go \
  saki-agent/internal/app/connect/delivery_client.go \
  saki-agent/internal/app/connect/delivery_client_test.go \
  saki-agent/internal/app/bootstrap/bootstrap.go \
  saki-agent/internal/app/bootstrap/bootstrap_test.go \
  saki-agent/internal/app/connect/client.go \
  saki-agent/cmd/agent/main.go \
  saki-agent/cmd/agent/main_test.go \
  saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go \
  saki-controlplane/internal/gen/proto \
  saki-agent/internal/gen/runtime
git commit -m "feat(runtime): add pull delivery closure for agent commands"
```

## Chunk 5: Recovery, Public API, And Deployment Surface

### Task 9: 增加 recovery role，处理失联 agent、未确认 assign、cancel 超时

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/app/recovery/worker.go`
- Create: `saki-controlplane/internal/modules/runtime/app/recovery/worker_test.go`
- Create: `saki-controlplane/internal/modules/runtime/app/recovery/policy.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/runtime/recovery_role.go`
- Modify: `saki-controlplane/db/queries/runtime/task.sql`
- Modify: `saki-controlplane/db/queries/runtime/agent.sql`
- Modify: `saki-controlplane/db/queries/runtime/task_assignment.sql`
- Modify: `saki-controlplane/db/queries/runtime/agent_command.sql`
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/agent_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_assignment_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/agent_command_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/recovery/worker_test.go`
- Test: `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go`

- [ ] **Step 1: 写失败测试，冻结恢复策略**

```go
func TestRecovery_RequeuesAssignedTaskWhenAssignNotAcked(t *testing.T) {}
func TestRecovery_FailsRunningTaskWhenAgentLost(t *testing.T) {}
func TestRecovery_ClosesStaleCancelWhenAgentOffline(t *testing.T) {}
```

最小策略冻结为：

1. `assigned` 且 assign command 长时间未 `acked`，重新置回 `pending`。
2. `running` 且 agent 超过 heartbeat timeout 失联，任务置为 `failed`，原因写 `agent_lost`。
3. `cancel_requested` 且 agent 已离线，任务直接置为 `canceled`。

- [ ] **Step 2: 运行 recovery/e2e 测试，确认当前没有独立恢复逻辑**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/recovery ./internal/modules/runtime/e2e -v`

Expected: FAIL，原因是当前只有 scheduler/outbox worker，没有 recovery role。

- [ ] **Step 3: 实现 recovery worker 与 repo 支持**

要求：

1. recovery worker 是独立 loop，不混入 scheduler。
2. 全部恢复动作都必须通过 repo 原子更新，不准扫描后内存改状态。
3. 恢复动作必须写明 `terminal_reason` 或 `last_error`，方便排障。

- [ ] **Step 4: 运行 recovery 与 e2e 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/recovery ./internal/modules/runtime/e2e -count=1 -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/app/recovery/worker.go \
  saki-controlplane/internal/modules/runtime/app/recovery/worker_test.go \
  saki-controlplane/internal/modules/runtime/app/recovery/policy.go \
  saki-controlplane/internal/modules/runtime/app/runtime/recovery_role.go \
  saki-controlplane/db/queries/runtime/task.sql \
  saki-controlplane/db/queries/runtime/agent.sql \
  saki-controlplane/db/queries/runtime/task_assignment.sql \
  saki-controlplane/db/queries/runtime/agent_command.sql \
  saki-controlplane/internal/modules/runtime/repo/task_repo.go \
  saki-controlplane/internal/modules/runtime/repo/agent_repo.go \
  saki-controlplane/internal/modules/runtime/repo/task_assignment_repo.go \
  saki-controlplane/internal/modules/runtime/repo/agent_command_repo.go \
  saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go
git commit -m "feat(runtime): add recovery loop for agent and command timeouts"
```

### Task 10: 把 public API、OpenAPI、部署配置全部切到 controlplane/agent 语义

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Modify: `saki-controlplane/internal/gen/openapi`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/list_executors.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go`
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `docker-compose.yml`
- Modify: `env.example`
- Modify: `README.md`
- Test: `saki-controlplane/internal/modules/system/apihttp -run TestPublicAPISmoke -v`

- [ ] **Step 1: 写失败测试，冻结外部 API 语义**

外部接口冻结为：

1. `GET /runtime/agents`
2. 保留 `GET /runtime/executors` 一个发布周期的兼容 alias
3. 返回模型名从 `RuntimeExecutor` 改为 `RuntimeAgent`

```go
func TestListRuntimeAgents(t *testing.T) {}
func TestListRuntimeExecutorsAliasStillWorks(t *testing.T) {}
```

- [ ] **Step 2: 运行 public API smoke test，确认当前外部语义仍是 executor/dispatcher**

Run: `cd saki-controlplane && make gen-openapi && go test ./internal/modules/system/apihttp -run TestPublicAPISmoke -v`

Expected: FAIL，原因是 openapi 和 handler 仍暴露 `/runtime/executors`。

- [ ] **Step 3: 改 API、生成代码，并更新部署文档**

部署面要求：

1. `docker-compose.yml` 中新增 `saki-controlplane-public-api`、`saki-controlplane-runtime`、`saki-agent` 服务名。
2. `saki-dispatcher` 和 `saki-executor` 保留过渡 profile 或直接移除，但 README 中必须明确迁移说明。
3. `env.example` 去掉 `DISPATCHER_*`、`EXECUTOR_*`，新增：

```env
RUNTIME_ROLES=ingress,scheduler,delivery,recovery
AGENT_TRANSPORT_MODE=pull
AGENT_MAX_CONCURRENCY=1
RUNTIME_AGENT_HEARTBEAT_TIMEOUT=30s
RUNTIME_ASSIGN_ACK_TIMEOUT=30s
```

- [ ] **Step 4: 重新生成 OpenAPI 并跑 smoke test**

Run: `cd saki-controlplane && make gen-openapi && go test ./internal/modules/system/apihttp -run TestPublicAPISmoke -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/openapi/public-api.yaml \
  saki-controlplane/internal/gen/openapi \
  saki-controlplane/internal/modules/runtime/apihttp/handlers.go \
  saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/runtime/app/queries/list_executors.go \
  saki-controlplane/internal/modules/runtime/app/queries/get_runtime_summary.go \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  docker-compose.yml \
  env.example \
  README.md
git commit -m "refactor(api): expose runtime agents and controlplane deployment surface"
```

## Chunk 6: Optional Relay Extraction

### Task 11: 在 `pull` 稳定后，再引入独立 relay 作为可选 delivery adapter

**Files:**
- Create: `saki-controlplane/api/proto/runtime/v1/agent_relay.proto`
- Create: `saki-agent/api/proto/runtime/v1/agent_relay.proto`
- Create: `saki-controlplane/cmd/relay/main.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/relay_server.go`
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/relay_server_test.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/agent_session_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/relay_transport.go`
- Modify: `saki-agent/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-agent/internal/app/connect/delivery_client.go`
- Modify: `saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/relay_server_test.go`
- Test: `saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go`

- [ ] **Step 1: 写失败测试，冻结 relay 边界**

```proto
service AgentRelay {
  rpc Open(stream RelayFrame) returns (stream RelayFrame);
}
```

限制条件：

1. relay 只管 session 和低延迟推送。
2. relay 不得自己生成 task 状态。
3. relay 掉线后 command 真相仍在 `agent_command`。

- [ ] **Step 2: 运行 relay 测试，确认当前 runtime 不支持 session relay**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/e2e -run 'TestAgentRelay|TestRuntimeAgentClosure' -v`

Expected: FAIL，原因是当前没有 `cmd/relay`、`agent_session`、`relay_transport`。

- [ ] **Step 3: 实现 relay 但不改变系统真相位置**

最小结构：

```go
type AgentSession struct {
    AgentID      string
    RelayID      string
    SessionID    string
    ConnectedAt  time.Time
    LastSeenAt   time.Time
}
```

规则：

1. `delivery` 看到 `transport_mode=relay` 时，把命令交给 `relay_transport`。
2. `relay_transport` 只根据 `agent_session` 把命令送到连接，不自己重排任务状态。
3. 若 relay 当前无 session，则保留命令为 `pending/retry`，等 agent 重连。

- [ ] **Step 4: 跑 relay 合同与闭环测试**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc ./internal/modules/runtime/e2e -count=1 -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/proto/runtime/v1/agent_relay.proto \
  saki-agent/api/proto/runtime/v1/agent_relay.proto \
  saki-controlplane/cmd/relay/main.go \
  saki-controlplane/internal/modules/runtime/internalrpc/relay_server.go \
  saki-controlplane/internal/modules/runtime/internalrpc/relay_server_test.go \
  saki-controlplane/internal/modules/runtime/repo/agent_session_repo.go \
  saki-controlplane/internal/modules/runtime/effects/relay_transport.go \
  saki-agent/internal/app/bootstrap/bootstrap.go \
  saki-agent/internal/app/connect/delivery_client.go \
  saki-controlplane/internal/modules/runtime/e2e/runtime_agent_closure_test.go \
  saki-controlplane/internal/gen/proto \
  saki-agent/internal/gen/runtime
git commit -m "feat(runtime): add optional relay transport adapter"
```

## Final Cleanup Checklist

- [ ] 删除 `RUNTIME_SCHEDULER_TARGET_AGENT`
- [ ] 删除 `RUNTIME_AGENT_CONTROL_BASE_URL`
- [ ] 删除旧 `runtime_executor` / `runtime_outbox` 读写路径
- [ ] 视兼容窗口决定是否删除旧表、旧 API alias、旧 env
- [ ] 统一所有测试和文档中的 `executor` 文案
- [ ] 在 `docker-compose.yml` 中默认启用 `pull`，`direct` 仅在本地调试 profile 中保留

## Verification Matrix

- `cd saki-controlplane && make gen && go test ./...`
- `cd saki-agent && make gen-proto && go test ./...`
- `cd saki-controlplane && go test ./internal/modules/runtime/... -count=1`
- `cd saki-agent && go test ./cmd/agent ./internal/app/runtime ./internal/app/connect -count=1`
- `cd saki-controlplane && make smoke-public-api`
- `cd saki-agent && make build-agent`
- `cd saki-controlplane && make build-public-api build-runtime`

## Suggested Execution Order

1. 先完成 Chunk 1，确保 role 与语义名词先稳定。
2. 再完成 Chunk 2，把真相从 `runtime_executor/runtime_outbox` 迁到 `agent/task_assignment/agent_command`。
3. 接着完成 Chunk 3 和 Chunk 4，跑通动态调度与 `pull` 闭环。
4. 再做 Chunk 5，补齐 recovery 和对外部署面。
5. 最后再评估是否真的需要 Chunk 6 的 relay。
