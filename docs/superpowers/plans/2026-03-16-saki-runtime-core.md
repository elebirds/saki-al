# Saki Runtime Core Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `runtime role` 的核心能力，包括单 leader 调度、`Task/Round/Loop` 状态机、agent 事件接入和 outbox 副作用链路。

**Architecture:** 先落 runtime 写模型与状态机，再接入调度 tick、leader lease、effect/outbox 和 ConnectRPC ingress。scheduler 只发 command，不直接跨层乱改状态。

**Tech Stack:** Go, `connect-go`, `buf`, `pgx/v5`, `sqlc`, Postgres lease, `slog`

---

## Chunk 1: Runtime Contracts And State Machines

### Task 1: Finalize runtime proto contracts

**Files:**
- Modify: `saki-controlplane/api/proto/runtime/v1/agent_control.proto`
- Modify: `saki-controlplane/api/proto/runtime/v1/agent_events.proto`
- Modify: `saki-controlplane/api/proto/runtime/v1/artifact.proto`
- Modify: `saki-controlplane/buf.gen.yaml`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_contract_test.go`

- [ ] **Step 1: Write a failing contract codec test for register/heartbeat/task-event payloads**
- [ ] **Step 2: Run `cd saki-controlplane && make gen-proto && go test ./internal/modules/runtime/internalrpc -v` and verify it fails**
- [ ] **Step 3: Finalize proto messages for `Register`, `Heartbeat`, `AssignTask`, `StopTask`, `TaskEventEnvelope`**
- [ ] **Step 4: Re-generate code and make tests pass**
- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/api/proto saki-controlplane/buf.gen.yaml saki-controlplane/internal/gen/proto
git commit -m "feat(runtime): finalize runtime rpc contracts"
```

### Task 2: Implement pure runtime state machines

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/state/task_machine.go`
- Create: `saki-controlplane/internal/modules/runtime/state/round_machine.go`
- Create: `saki-controlplane/internal/modules/runtime/state/loop_machine.go`
- Test: `saki-controlplane/internal/modules/runtime/state/task_machine_test.go`
- Test: `saki-controlplane/internal/modules/runtime/state/round_machine_test.go`
- Test: `saki-controlplane/internal/modules/runtime/state/loop_machine_test.go`

- [ ] **Step 1: Write failing tests for valid and invalid state transitions**

```go
func TestTaskMachine_StartPendingTask(t *testing.T) {}
func TestTaskMachine_RejectFinishFromPending(t *testing.T) {}
```

- [ ] **Step 2: Run `cd saki-controlplane && go test ./internal/modules/runtime/state -v` and verify it fails**
- [ ] **Step 3: Implement `Command -> DomainEvent -> Evolve(State)` for task/round/loop**
- [ ] **Step 4: Re-run state machine tests and make them pass**
- [ ] **Step 5: Commit**

```bash
git add saki-controlplane/internal/modules/runtime/state
git commit -m "feat(runtime): add core state machines"
```

## Chunk 2: Persistence, Scheduler, And Effects

### Task 3: Add runtime tables, queries, and repositories

**Files:**
- Create: `saki-controlplane/db/migrations/000030_runtime_tables.sql`
- Create: `saki-controlplane/db/queries/runtime/lease.sql`
- Create: `saki-controlplane/db/queries/runtime/task.sql`
- Create: `saki-controlplane/db/queries/runtime/outbox.sql`
- Create: `saki-controlplane/internal/modules/runtime/repo/task_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/round_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/loop_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/lease_repo.go`
- Create: `saki-controlplane/internal/modules/runtime/repo/outbox_repo.go`
- Test: `saki-controlplane/internal/modules/runtime/repo/runtime_repo_test.go`

- [ ] **Step 1: Write failing integration tests for claim/lease/outbox operations**
- [ ] **Step 2: Run runtime repo tests to verify failure**
- [ ] **Step 3: Add SQL for lease acquire/renew, task claim, task status update, outbox append**
- [ ] **Step 4: Wrap generated queries in runtime repos and make tests pass**
- [ ] **Step 5: Commit**

### Task 4: Implement command handlers and scheduler

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/app/commands/assign_task.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/register_executor.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/heartbeat_executor.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/complete_task.go`
- Create: `saki-controlplane/internal/modules/runtime/app/commands/advance_round.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/leader.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/tick.go`
- Create: `saki-controlplane/internal/modules/runtime/app/scheduler/dispatch_scan.go`
- Test: `saki-controlplane/internal/modules/runtime/app/scheduler/tick_test.go`
- Test: `saki-controlplane/internal/modules/runtime/app/commands/assign_task_test.go`

- [ ] **Step 1: Write failing tests for `AssignTaskCommand` and leader tick behavior**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Implement command handlers that load snapshots, call state machines, persist changes, and append outbox events**
- [ ] **Step 4: Implement scheduler that acquires lease, scans candidates, and emits commands without directly mutating state**
- [ ] **Step 5: Re-run tests and commit**

```bash
git add saki-controlplane/internal/modules/runtime/app
git commit -m "feat(runtime): add command handlers and scheduler"
```

### Task 5: Implement ConnectRPC ingress and effects

**Files:**
- Create: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/readmodel_effect.go`
- Create: `saki-controlplane/internal/modules/runtime/effects/stream_effect.go`
- Test: `saki-controlplane/internal/modules/runtime/internalrpc/runtime_server_test.go`
- Test: `saki-controlplane/internal/modules/runtime/effects/dispatch_effect_test.go`

- [ ] **Step 1: Write failing tests for register/heartbeat/task-event ingestion**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement Connect handlers that translate RPC payloads into app commands**
- [ ] **Step 4: Implement outbox-driven effects for assign/stop/readmodel/event-stream**
- [ ] **Step 5: Run `cd saki-controlplane && go test ./internal/modules/runtime/... -v` and commit**

```bash
git add saki-controlplane/internal/modules/runtime/internalrpc saki-controlplane/internal/modules/runtime/effects
git commit -m "feat(runtime): add ingress and effect pipeline"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-runtime-core.md`. Ready to execute?
