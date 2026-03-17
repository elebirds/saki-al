# Saki Runtime Core Closure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `saki-controlplane` 的 `runtime role` 从“骨架 + 样板”收口为一条真实可运行的 task 主干链路，并与 `2026-03-17-saki-skeleton-phase-frozen-decisions-design.md` 完全对齐。

**Architecture:** 先收敛 runtime 契约，再补 runtime role 的真实 wiring，最后用一条最小端到端链路验证 `pending -> assigned -> running -> terminal` 与 `public-api -> cancel` 的正式路径。不要在本计划中扩业务面；本计划只解决 runtime 作为后续完整迁移落点的问题。

**Tech Stack:** Go, connect-go, buf, pgx/v5, sqlc, goose, slog, testcontainers-go

---

## Chunk 1: Runtime Contract Convergence

### Task 1: 把 Task 状态机收敛到冻结语义

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/state/task_machine.go`
- Modify: `saki-controlplane/internal/modules/runtime/state/task_machine_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/complete_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/cancel_task.go`
- Test: `saki-controlplane/internal/modules/runtime/state/task_machine_test.go`

- [ ] **Step 1: 写失败测试，明确正式状态集合与主线迁移**

```go
func TestTaskMachine_AssignPendingTask(t *testing.T) {}
func TestTaskMachine_StartAssignedTask(t *testing.T) {}
func TestTaskMachine_RequestCancelRunningTask(t *testing.T) {}
func TestTaskMachine_RejectFinishFromAssigned(t *testing.T) {}
```

- [ ] **Step 2: 运行状态机测试，确认当前语义不匹配**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/state -run TestTaskMachine -v`
Expected: FAIL，原因是当前状态机仍使用 `pending/running/...` 的原型迁移，尚未覆盖 `assigned/cancel_requested`。

- [ ] **Step 3: 将状态机改为冻结语义**

```go
const (
    TaskStatusPending         TaskStatus = "pending"
    TaskStatusAssigned        TaskStatus = "assigned"
    TaskStatusRunning         TaskStatus = "running"
    TaskStatusCancelRequested TaskStatus = "cancel_requested"
    TaskStatusSucceeded       TaskStatus = "succeeded"
    TaskStatusFailed          TaskStatus = "failed"
    TaskStatusCanceled        TaskStatus = "canceled"
)
```

新增清晰命令/事件，不再复用原型命名：

```go
type AssignTask struct{}
type StartTaskExecution struct{}
type RequestTaskCancel struct{}
type FinishTask struct{}
type FailTask struct{}
type ConfirmTaskCanceled struct{}
```

- [ ] **Step 4: 调整 command handler 以匹配新状态**

要求：

1. `AssignTaskHandler` 的领域迁移必须是 `pending -> assigned`。
2. `CompleteTaskHandler` 只能处理 `running -> succeeded`。
3. `CancelTaskHandler` 只能发出 `cancel_requested` 或 `pending -> canceled`，不得直接把运行中任务写成终态。

- [ ] **Step 5: 重新运行状态机和 command 单测**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/state ./internal/modules/runtime/app/commands -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/state/task_machine.go \
  saki-controlplane/internal/modules/runtime/state/task_machine_test.go \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go \
  saki-controlplane/internal/modules/runtime/app/commands/complete_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/cancel_task.go
git commit -m "feat(runtime): converge task state machine semantics"
```

### Task 2: 对齐 runtime_task 与 runtime_outbox 的最小正式 schema

**Files:**
- Create: `saki-controlplane/db/migrations/000031_runtime_core_alignment.sql`
- Modify: `saki-controlplane/db/queries/runtime/task.sql`
- Modify: `saki-controlplane/db/queries/runtime/outbox.sql`
- Modify: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/outbox_repo.go`
- Modify: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`
- Test: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`

- [ ] **Step 1: 写失败的 repo 集成测试，锁定新字段语义**

```go
func TestTaskRepoAssignsExecutionAndAgent(t *testing.T) {}
func TestOutboxRepoClaimsAndMarksPublished(t *testing.T) {}
```

至少验证：

1. `runtime_task` 持有 `task_kind/current_execution_id/assigned_agent_id/attempt/max_attempts/resolved_params/depends_on_task_ids/leader_epoch`。
2. `runtime_outbox` 持有 `aggregate_type/idempotency_key/available_at/attempt_count/published_at/last_error`。

- [ ] **Step 2: 运行 repo 测试，确认当前 schema 不足**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/repo -run 'TestTaskRepoAssignsExecutionAndAgent|TestOutboxRepoClaimsAndMarksPublished' -v`
Expected: FAIL，原因是当前表结构和 query 尚未承载冻结字段。

- [ ] **Step 3: 新增 runtime schema 对齐迁移**

迁移目标：

1. 为 `runtime_task` 增加缺失字段，不再使用 `claimed_by` 承担混合语义。
2. 为 `runtime_outbox` 增加 effect queue 所需字段。
3. 保留现有 `runtime_lease` 结构，不在此任务中重做 lease 表。

- [ ] **Step 4: 改写 task/outbox SQL 与 repo**

要求：

1. 把 `dispatching` 全部替换为 `assigned`。
2. `Assign` query 一次性完成 candidate claim、`execution_id` 生成、`assigned_agent_id` 绑定、`leader_epoch` 写入。
3. outbox 必须支持 claim due、mark published、mark retry。

- [ ] **Step 5: 运行 sqlc 生成与 repo 测试**

Run: `cd saki-controlplane && make gen-sqlc && go test ./internal/modules/runtime/repo -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add \
  saki-controlplane/db/migrations/000031_runtime_core_alignment.sql \
  saki-controlplane/db/queries/runtime/task.sql \
  saki-controlplane/db/queries/runtime/outbox.sql \
  saki-controlplane/internal/modules/runtime/repo/task_repo.go \
  saki-controlplane/internal/modules/runtime/repo/outbox_repo.go \
  saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go
git commit -m "feat(runtime): align task and outbox persistence"
```

### Task 3: 拆分 Runtime/Agent 的双向 RPC 合同

**Files:**
- Create: `saki-controlplane/api/proto/runtime/v1/agent_ingress.proto`
- Modify: `saki-controlplane/api/proto/runtime/v1/agent_control.proto`
- Modify: `saki-controlplane/api/proto/runtime/v1/agent_events.proto`
- Modify: `saki-controlplane/buf.gen.yaml`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`

- [ ] **Step 1: 写失败的合同测试，分别覆盖 ingress/control**

```go
func TestAgentIngressRegisterCodec(t *testing.T) {}
func TestAgentIngressTaskEventEnvelopeCodec(t *testing.T) {}
func TestAgentControlAssignTaskCodec(t *testing.T) {}
```

- [ ] **Step 2: 运行 proto 合同测试，确认当前 service 方向混用**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc -run 'TestAgentIngress|TestAgentControl' -v`
Expected: FAIL，原因是当前 `AgentControl` 仍混合了 ingress/control 两个方向。

- [ ] **Step 3: 拆分 proto service**

冻结后的方向：

1. `AgentIngress`：`Register`、`Heartbeat`、`PushTaskEvent`
2. `AgentControl`：`AssignTask`、`StopTask`

保留说明：

1. `artifact ticket`、`runtime update command` 仍属于 Runtime/Agent RPC，但暂不在本任务内定具体 service/method。

- [ ] **Step 4: 重新生成代码并修正合同测试**

Run: `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/api/proto/runtime/v1/agent_ingress.proto \
  saki-controlplane/api/proto/runtime/v1/agent_control.proto \
  saki-controlplane/api/proto/runtime/v1/agent_events.proto \
  saki-controlplane/buf.gen.yaml \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go \
  saki-controlplane/internal/gen/proto
git commit -m "feat(runtime): split ingress and control rpc contracts"
```

## Chunk 2: Make Runtime Role Real

### Task 4: 闭合 scheduler -> command -> repo -> outbox 主链路

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/tick.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/scheduler/tick_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan_test.go`

- [ ] **Step 1: 写失败测试，锁定 assign 主链路的唯一入口**

```go
func TestDispatchScanClaimsPendingTaskAndAppendsAssignOutbox(t *testing.T) {}
func TestLeaderTickSkipsWhenLeaseNotOwned(t *testing.T) {}
```

- [ ] **Step 2: 运行 scheduler 测试，确认当前 `NextPendingTask` 原型接口已过时**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/scheduler ./internal/modules/runtime/app/commands -v`
Expected: FAIL，原因是当前 `scheduler -> command -> repo` 尚未共享同一接口与 payload。

- [ ] **Step 3: 重写 assign 链路**

要求：

1. 去掉 `NextPendingTask()` 这类与 repo 脱节的原型接口。
2. 由 command handler 调用真实 repo claim。
3. claim 结果必须生成正式 `runtime.task.assign.v1` outbox payload。

- [ ] **Step 4: 重新运行 scheduler/command 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/scheduler ./internal/modules/runtime/app/commands -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan_test.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/tick.go \
  saki-controlplane/internal/modules/runtime/app/scheduler/tick_test.go \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go
git commit -m "feat(runtime): close scheduler to outbox assign path"
```

### Task 5: 实现 runtime outbox worker 与 assign/stop effect

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/effects/worker.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/stop_effect.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect.go`
- Modify: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/stop_effect_test.go`
- Test: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go`
- Test: `saki-controlplane/internal/modules/runtime/effects/stop_effect_test.go`

- [ ] **Step 1: 写失败测试，验证 assign/stop 读取正式 outbox payload**

```go
func TestDispatchEffectAssignTaskTopicInvokesControlClient(t *testing.T) {}
func TestStopEffectStopTaskTopicInvokesControlClient(t *testing.T) {}
```

- [ ] **Step 2: 运行 effect 测试，确认当前 payload 不兼容**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/effects -v`
Expected: FAIL，原因是当前 outbox payload 仍是原型结构，且没有 stop effect/worker。

- [ ] **Step 3: 实现 outbox worker**

要求：

1. claim due records
2. 按 topic 分发 effect
3. 成功后 mark published
4. 失败后累加 attempt 并记录 error

- [ ] **Step 4: 重新运行 effect 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/effects -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/effects/worker.go \
  saki-controlplane/internal/modules/runtime/effects/stop_effect.go \
  saki-controlplane/internal/modules/runtime/effects/stop_effect_test.go \
  saki-controlplane/internal/modules/runtime/effects/dispatch_effect.go \
  saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go
git commit -m "feat(runtime): add outbox worker and control effects"
```

### Task 6: 让 runtime ingress 真正消费 `execution_id` 驱动的任务事件

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go`
- Modify: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/start_task.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/fail_task.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/commands/complete_task.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`

- [ ] **Step 1: 写失败测试，覆盖 `RUNNING/SUCCEEDED/FAILED/CANCELED` 与 `execution_id` fencing**

```go
func TestAgentIngressRunningEventStartsAssignedTask(t *testing.T) {}
func TestAgentIngressIgnoresStaleExecutionID(t *testing.T) {}
func TestAgentIngressFailedEventMarksTaskFailed(t *testing.T) {}
func TestAgentIngressCanceledEventMarksTaskCanceled(t *testing.T) {}
```

- [ ] **Step 2: 运行 ingress 测试，确认当前只消费 succeeded 事件**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/internalrpc -v`
Expected: FAIL，原因是当前实现没有 `RUNNING/FAILED/CANCELED` 分支，也没有 `execution_id` 校验。

- [ ] **Step 3: 实现正式 ingress handler**

要求：

1. `RUNNING` 推进 `assigned -> running`
2. `SUCCEEDED` 推进 `running/cancel_requested -> succeeded`
3. `FAILED` 推进 `running/cancel_requested -> failed`
4. `CANCELED` 推进 `cancel_requested -> canceled`
5. 所有分支都必须校验 `task_id + execution_id`

- [ ] **Step 4: 重新运行 ingress 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/internalrpc -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go \
  saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go \
  saki-controlplane/internal/modules/runtime/app/commands/start_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/fail_task.go \
  saki-controlplane/internal/modules/runtime/app/commands/complete_task.go
git commit -m "feat(runtime): consume task events with execution fencing"
```

## Chunk 3: Wire The Real Runtime Role

### Task 7: 将 `cmd/runtime` 从 healthz 壳子接成真实 runtime role

**Files:**
- Modify: `saki-controlplane/internal/app/bootstrap/bootstrap.go`
- Modify: `saki-controlplane/cmd/runtime/main.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/runner.go`
- Create: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go`

- [ ] **Step 1: 写失败测试，验证 runtime role 装配最小必需组件**

```go
func TestRuntimeRunnerStartsIngressSchedulerAndOutboxWorker(t *testing.T) {}
```

至少验证：

1. runtime server 暴露 ingress handler
2. scheduler loop 被装配
3. outbox worker 被装配

- [ ] **Step 2: 运行 runtime runner 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/runtime -v`
Expected: FAIL，原因是当前 `NewRuntime()` 仍只有 healthz。

- [ ] **Step 3: 实现 runtime role bootstrap**

要求：

1. 建 DB pool
2. 装配 lease repo / task repo / outbox repo
3. 装配 command handler / scheduler / ingress server / effect worker
4. 保留 healthz，但它不能再是 runtime role 的唯一能力

- [ ] **Step 4: 运行 runtime runner 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/app/runtime -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/app/bootstrap/bootstrap.go \
  saki-controlplane/cmd/runtime/main.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner.go \
  saki-controlplane/internal/modules/runtime/app/runtime/runner_test.go
git commit -m "feat(runtime): wire real runtime role"
```

### Task 8: 把 `public-api -> cancel task` 绑定到正式 runtime 路径

**Files:**
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers.go`
- Modify: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`
- Modify: `saki-controlplane/internal/modules/runtime/app/queries/issue_runtime_command.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Test: `saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go`

- [ ] **Step 1: 写失败测试，验证 cancel 只走 runtime command/outbox**

```go
func TestCancelRuntimeTaskUsesCommandPathAndWritesStopOutbox(t *testing.T) {}
```

- [ ] **Step 2: 运行 runtime api 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/apihttp -v`
Expected: FAIL，原因是当前 cancel 还没有落到正式 `cancel_requested + stop outbox` 路径。

- [ ] **Step 3: 实现正式 cancel 路径**

要求：

1. pending task 可直接到 `canceled`
2. assigned/running task 要进入 `cancel_requested`
3. 只有需要通知 agent 的取消才写 `runtime.task.stop.v1`

- [ ] **Step 4: 运行 runtime api 测试**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/apihttp -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/apihttp/handlers.go \
  saki-controlplane/internal/modules/runtime/apihttp/handlers_test.go \
  saki-controlplane/internal/modules/runtime/app/queries/issue_runtime_command.go \
  saki-controlplane/internal/modules/system/apihttp/server.go
git commit -m "feat(runtime): route cancel through runtime command path"
```

### Task 9: 写一条最小端到端回归，宣布 runtime 主干收口

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go`
- Modify: `saki-controlplane/Makefile`
- Test: `saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go`

- [ ] **Step 1: 写失败的端到端回归**

```go
func TestRuntimeTaskLifecycle_AssignRunSucceed(t *testing.T) {}
func TestRuntimeTaskLifecycle_CancelPathWritesStopOutbox(t *testing.T) {}
```

第一条只要求覆盖任一终态主线：

1. seed pending task
2. leader tick
3. assign outbox
4. ingress running
5. ingress succeeded

第二条覆盖：

1. assigned/running task
2. public-api cancel
3. stop outbox

- [ ] **Step 2: 运行端到端回归**

Run: `cd saki-controlplane && go test ./internal/modules/runtime/e2e -v`
Expected: FAIL，直到前序任务全部收口。

- [ ] **Step 3: 修 Makefile，把 runtime 主链路验证纳入常规测试入口**

建议加入：

```make
test-runtime:
	go test ./internal/modules/runtime/... ./internal/modules/runtime/e2e/...
```

- [ ] **Step 4: 运行完整 runtime 测试**

Run: `cd saki-controlplane && make test-runtime`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  saki-controlplane/internal/modules/runtime/e2e/runtime_task_lifecycle_test.go \
  saki-controlplane/Makefile
git commit -m "test(runtime): add task lifecycle end-to-end coverage"
```

## Follow-On Plans

本计划完成后，不要直接“全面开写剩余迁移”，而是按以下顺序继续写后续 plans：

1. `saki-agent` 与 `AgentControl` 的对接计划
2. `public-api` 做实计划
3. `annotation + mapping sidecar` 最小纵向切片计划
4. `import/export` 迁移与旧系统退役计划

只有在本计划完成后，后续三类迁移才有稳定的 runtime 落点。

Plan complete and saved to `docs/superpowers/plans/2026-03-17-saki-runtime-core-closure.md`. Ready to execute?
