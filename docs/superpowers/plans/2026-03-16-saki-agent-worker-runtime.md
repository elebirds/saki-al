# Saki Agent And Worker Runtime Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现新的 `saki-agent`、本地 `worker proto`、Python plugin worker 适配层，以及 controlplane 侧 `annotation mapping engine` 的 sidecar 调用链路。

**Architecture:** `controlplane` 只和 `agent` 通信，`agent` 负责本地执行与 worker 生命周期，Python worker 只负责算法执行。annotation mapping engine 作为 controlplane 本地 sidecar/子进程，而不是 runtime agent 插件。

**Tech Stack:** Go, `connect-go`, Protobuf, stdio framed protocol, Python, `uv`, OpenCV/NumPy

---

## Chunk 1: Go Agent Skeleton And Worker Protocol

### Task 1: Create the `saki-agent` project skeleton

**Files:**
- Create: `saki-agent/go.mod`
- Create: `saki-agent/Makefile`
- Create: `saki-agent/cmd/agent/main.go`
- Create: `saki-agent/internal/app/connect/client.go`
- Create: `saki-agent/internal/plugins/protocol/frame.go`
- Create: `saki-agent/internal/runtime/workspace/workspace.go`
- Test: `saki-agent/internal/plugins/protocol/frame_test.go`

- [ ] **Step 1: Write a failing frame encode/decode test**
- [ ] **Step 2: Run `cd saki-agent && go test ./internal/plugins/protocol -v` and verify failure**
- [ ] **Step 3: Implement length-delimited framed message protocol**
- [ ] **Step 4: Add minimal agent bootstrap and runtime client skeleton**
- [ ] **Step 5: Commit**

```bash
git add saki-agent
git commit -m "feat(agent): add agent foundation skeleton"
```

### Task 2: Define worker proto and generated bindings

**Files:**
- Modify: `saki-controlplane/api/proto/worker/v1/worker.proto`
- Create: `saki-agent/internal/gen/worker/.gitkeep`
- Create: `saki-plugin-sdk/src/saki_plugin_sdk/worker_protocol.py`
- Test: `saki-agent/internal/plugins/protocol/worker_proto_test.go`

- [ ] **Step 1: Write failing tests for worker request/response/event envelopes**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Finalize worker proto with `ExecuteRequest`, `WorkerEvent`, `ExecuteResult`**
- [ ] **Step 4: Generate Go/Python bindings and make tests pass**
- [ ] **Step 5: Commit**

## Chunk 2: Worker Lifecycle And Mapping Engine

### Task 3: Implement plugin worker lifecycle in agent

**Files:**
- Create: `saki-agent/internal/plugins/launcher/launcher.go`
- Create: `saki-agent/internal/plugins/launcher/process.go`
- Create: `saki-agent/internal/runtime/task_runner/runner.go`
- Create: `saki-agent/internal/app/reporting/events.go`
- Test: `saki-agent/internal/plugins/launcher/launcher_test.go`
- Test: `saki-agent/internal/runtime/task_runner/runner_test.go`

- [ ] **Step 1: Write failing tests for ephemeral worker start/stop and event forwarding**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Implement subprocess launch, stdio framing, timeout handling, and event forwarding**
- [ ] **Step 4: Wire worker execution into agent task runner**
- [ ] **Step 5: Run tests and commit**

```bash
git add saki-agent/internal/plugins saki-agent/internal/runtime saki-agent/internal/app
git commit -m "feat(agent): add plugin worker lifecycle"
```

### Task 4: Adapt Python plugin SDK to worker mode

**Files:**
- Create: `saki-plugin-sdk/src/saki_plugin_sdk/worker_main.py`
- Create: `saki-plugin-sdk/src/saki_plugin_sdk/worker_runtime.py`
- Modify: `saki-plugin-sdk/src/saki_plugin_sdk/__init__.py`
- Test: `saki-plugin-sdk/tests/test_worker_runtime.py`

- [ ] **Step 1: Write failing Python tests for execute-request to execute-result flow**
- [ ] **Step 2: Run `cd saki-plugin-sdk && uv run pytest tests/test_worker_runtime.py -v` and verify failure**
- [ ] **Step 3: Implement worker-side protocol adapter and event emitter**
- [ ] **Step 4: Re-run Python tests and make them pass**
- [ ] **Step 5: Commit**

### Task 5: Add controlplane-side mapping engine sidecar

**Files:**
- Create: `saki-controlplane/internal/modules/annotation/app/mapping/client.go`
- Create: `saki-controlplane/internal/modules/annotation/app/mapping/process.go`
- Create: `saki-controlplane/internal/modules/annotation/app/mapping/protocol.go`
- Create: `saki-mapping-engine/pyproject.toml`
- Create: `saki-mapping-engine/src/saki_mapping_engine/__init__.py`
- Create: `saki-mapping-engine/src/saki_mapping_engine/worker_main.py`
- Create: `saki-mapping-engine/src/saki_mapping_engine/fedo_mapper.py`
- Test: `saki-controlplane/internal/modules/annotation/app/mapping/client_test.go`

- [ ] **Step 1: Write failing tests for controlplane calling local mapping sidecar and receiving normalized geometry**
- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Extract current FEDO/OpenCV mapping logic into a standalone Python mapping engine package**
- [ ] **Step 4: Implement Go-side sidecar client with stdio framed worker proto**
- [ ] **Step 5: Run tests and commit**

```bash
git add saki-controlplane/internal/modules/annotation/app/mapping saki-mapping-engine
git commit -m "feat(annotation): add local mapping engine sidecar"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-agent-worker-runtime.md`. Ready to execute?
