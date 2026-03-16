# Saki Import And Go-Native Adapters Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `shared/saki-ir/go` 中落地 Go-native `COCO / YOLO` annotation adapters，并在 `saki-controlplane` 中建立新的 `project annotation import` 最小闭环，保留 `upload session -> prepare -> execute -> task/result/events` 的长期交互模型。

**Architecture:** 先完成 `saki-ir/go` 的 format adapter 基础类型、转换报告和 `COCO bbox` / `YOLO det txt` 解析能力；然后在 `saki-controlplane/internal/modules/importing` 中建立 upload session、preview manifest、sample matching、execute task 与 SSE 事件流；最后把新的 import API 接入 `public-api`，并用 smoke 测试固定闭环行为。`IR Core` 继续只保留 `rect + obb`，复杂几何仅在 capability matrix 中设计留口，不在本阶段实现。

**Tech Stack:** Go 1.26, `ogen`, `pgx/v5`, `sqlc`, `goose`, PostgreSQL, Server-Sent Events, shared `saki-ir/go`

---

## Chunk 1: `saki-ir/go` Adapter Foundation

### Task 1: 建立通用 parse result / conversion report / geometry capability 基础类型

**Files:**
- Create: `shared/saki-ir/go/formats/common/result.go`
- Create: `shared/saki-ir/go/formats/common/result_test.go`
- Create: `shared/saki-ir/go/formats/common/sample_ref.go`
- Create: `shared/saki-ir/go/formats/common/report.go`
- Create: `shared/saki-ir/go/formats/common/geometry.go`
- Create: `shared/saki-ir/go/formats/common/testdata/.keep`
- Modify: `shared/saki-ir/go/go.mod`

- [ ] **Step 1: 先为 parse result、sample ref、geometry capability 与 conversion report 写失败测试，覆盖 `dataset_relpath`、`sample_name`、`basename` 三层匹配引用和 `rect / obb_xywhr / obb_poly8` capability 表达。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./...` 于 `shared/saki-ir/go`，确认新测试先失败。**
- [ ] **Step 3: 实现通用基础类型，要求 adapter 返回 `IR batch + sample refs + report + geometry capability`，但不让这些元信息污染 `IR Core proto`。**
- [ ] **Step 4: 补充 normalize/validation 约束，明确 `poly8` 只作为输入几何形态存在，进入 IR 后必须转换成 `obb`。**
- [ ] **Step 5: 重新运行 `shared/saki-ir/go` 全量测试并确认通过。**
- [ ] **Step 6: Commit。**

```bash
git add shared/saki-ir/go
git commit -m "feat(ir): add import adapter foundation"
```

### Task 2: 实现 `COCO bbox -> IR rect` adapter

**Files:**
- Create: `shared/saki-ir/go/formats/coco/parser.go`
- Create: `shared/saki-ir/go/formats/coco/parser_test.go`
- Create: `shared/saki-ir/go/formats/coco/types.go`
- Create: `shared/saki-ir/go/formats/coco/testdata/bbox/annotations.json`
- Create: `shared/saki-ir/go/formats/coco/testdata/bbox/images/.keep`

- [ ] **Step 1: 为 `COCO bbox` 解析写失败测试，覆盖 `images[].file_name -> dataset_relpath`、category label 归一化、bbox 到 `IR.rect`、以及 unsupported segmentation 的 capability 报告。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./formats/coco -v` 于 `shared/saki-ir/go`，确认失败。**
- [ ] **Step 3: 实现 COCO detection subset 解析器，只支持 bbox，不实现 segmentation/keypoints/crowd 扩展。**
- [ ] **Step 4: 让 parser 输出 `ParseProjectAnnotationsResult`，并在 report 中记录 detected/unsupported geometry kinds 与 raw sample refs。**
- [ ] **Step 5: 重新运行 `go test ./formats/coco -v` 与 `go test ./...` 于 `shared/saki-ir/go`，确认通过。**
- [ ] **Step 6: Commit。**

```bash
git add shared/saki-ir/go/formats/coco
git commit -m "feat(ir): add coco annotation adapter"
```

## Chunk 2: `YOLO` Adapter 与 Geometry 留口

### Task 3: 实现 `YOLO det txt -> IR rect` adapter，并保留 OBB 设计口

**Files:**
- Create: `shared/saki-ir/go/formats/yolo/parser.go`
- Create: `shared/saki-ir/go/formats/yolo/parser_test.go`
- Create: `shared/saki-ir/go/formats/yolo/types.go`
- Create: `shared/saki-ir/go/formats/yolo/testdata/det/data.yaml`
- Create: `shared/saki-ir/go/formats/yolo/testdata/det/labels/train/sample1.txt`
- Create: `shared/saki-ir/go/formats/yolo/testdata/det/images/train/.keep`

- [ ] **Step 1: 为 YOLO detection parser 写失败测试，覆盖 yaml/class names 读取、label 文件到 image `dataset_relpath` 推导、归一化坐标到 `IR.rect`，并显式测试 `obb_xywhr` / `obb_poly8` 只报告 unsupported、不执行转换。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./formats/yolo -v` 于 `shared/saki-ir/go`，确认失败。**
- [ ] **Step 3: 实现 YOLO det txt parser，只支持普通检测框格式，并把未来 OBB 支持留在 capability/report 中。**
- [ ] **Step 4: 复用 `formats/common` 的 result/report 类型，保证 COCO 与 YOLO adapter 输出形态一致。**
- [ ] **Step 5: 重新运行 `go test ./formats/yolo -v` 与 `go test ./...` 于 `shared/saki-ir/go`，确认通过。**
- [ ] **Step 6: Commit。**

```bash
git add shared/saki-ir/go/formats/yolo
git commit -m "feat(ir): add yolo annotation adapter"
```

## Chunk 3: `saki-controlplane/importing` 持久化与领域基础

### Task 4: 建立 import schema、sample match ref 与 repo 基础

**Files:**
- Create: `saki-controlplane/db/migrations/000050_import_tables.sql`
- Create: `saki-controlplane/db/queries/importing/upload.sql`
- Create: `saki-controlplane/db/queries/importing/preview.sql`
- Create: `saki-controlplane/db/queries/importing/task.sql`
- Create: `saki-controlplane/db/queries/importing/sample_match_ref.sql`
- Create: `saki-controlplane/internal/modules/importing/domain/upload.go`
- Create: `saki-controlplane/internal/modules/importing/domain/preview.go`
- Create: `saki-controlplane/internal/modules/importing/domain/task.go`
- Create: `saki-controlplane/internal/modules/importing/repo/upload_repo.go`
- Create: `saki-controlplane/internal/modules/importing/repo/preview_repo.go`
- Create: `saki-controlplane/internal/modules/importing/repo/task_repo.go`
- Create: `saki-controlplane/internal/modules/importing/repo/sample_match_ref_repo.go`
- Create: `saki-controlplane/internal/modules/importing/repo/repo_test.go`
- Modify: `saki-controlplane/db/sqlc.yaml`

- [ ] **Step 1: 为 import upload session、preview manifest、task/task event、sample_match_ref repo 写失败测试，覆盖 session 生命周期、preview token 查找、task event append 和 `dataset_relpath` 精确匹配。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/importing/repo -v` 于 `saki-controlplane`，确认失败。**
- [ ] **Step 3: 新增 `000050_import_tables.sql`，至少包含 `import_upload_session`、`import_preview_manifest`、`import_task`、`import_task_event`、`sample_match_ref` 五类表。**
- [ ] **Step 4: 编写 import SQL 文件并运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make check-gen` 于 `saki-controlplane` 更新 `sqlc` 产物。**
- [ ] **Step 5: 实现 repo，并约束 `sample_match_ref` 的主精确匹配键为 `dataset_relpath`，次级兼容键为 `sample_name`。**
- [ ] **Step 6: 重新运行 import repo 测试与 `make check-gen`，确认通过。**
- [ ] **Step 7: Commit。**

```bash
git add saki-controlplane/db/migrations/000050_import_tables.sql saki-controlplane/db/queries/importing saki-controlplane/db/sqlc.yaml saki-controlplane/internal/modules/importing
git commit -m "feat(import): add persistence foundation"
```

### Task 5: 实现 `prepare` 用例、样本匹配与 manifest 生成

**Files:**
- Create: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations.go`
- Create: `saki-controlplane/internal/modules/importing/app/matching.go`
- Create: `saki-controlplane/internal/modules/importing/app/matching_test.go`
- Create: `saki-controlplane/internal/modules/importing/app/prepare_project_annotations_test.go`
- Create: `saki-controlplane/internal/modules/importing/app/parser_registry.go`
- Modify: `saki-controlplane/internal/modules/project/repo/project_repo.go`
- Modify: `saki-controlplane/internal/modules/annotation/repo/sample_repo.go`

- [ ] **Step 1: 先为 prepare 用例和 sample matching 写失败测试，覆盖 `dataset_relpath` 精确匹配、`sample_name` 次级匹配、`basename` fallback、ambiguous 阻断、unsupported geometry 阻断。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/importing/app -v` 于 `saki-controlplane`，确认失败。**
- [ ] **Step 3: 实现 parser registry，把 `COCO / YOLO` adapter 作为 `project annotation import` 的唯一解析入口。**
- [ ] **Step 4: 实现 prepare 用例，要求只做 dry-run：解析 archive、样本匹配、label planning、capability 检查，并写入 preview manifest + `preview_token`。**
- [ ] **Step 5: 明确 mixed supported/unsupported 内容默认整批阻断，不做部分成功。**
- [ ] **Step 6: 重新运行 import app 测试并确认通过。**
- [ ] **Step 7: Commit。**

```bash
git add saki-controlplane/internal/modules/importing/app saki-controlplane/internal/modules/project/repo/project_repo.go saki-controlplane/internal/modules/annotation/repo/sample_repo.go
git commit -m "feat(import): add prepare flow and sample matching"
```

## Chunk 4: Execute、Task Runner 与 Public API

### Task 6: 实现 `execute`、annotation apply 与 import task/events

**Files:**
- Create: `saki-controlplane/internal/modules/importing/app/execute_project_annotations.go`
- Create: `saki-controlplane/internal/modules/importing/app/task_runner.go`
- Create: `saki-controlplane/internal/modules/importing/app/execute_project_annotations_test.go`
- Create: `saki-controlplane/internal/modules/importing/app/task_runner_test.go`
- Modify: `saki-controlplane/internal/modules/annotation/repo/annotation_repo.go`
- Modify: `saki-controlplane/internal/modules/annotation/app/create_annotation.go`

- [ ] **Step 1: 为 execute 与 task runner 写失败测试，覆盖 preview token 校验、blocking errors 拒绝执行、整批 annotation apply、task status/result/events 写入。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/importing/app -run 'TestExecute|TestTaskRunner' -v` 于 `saki-controlplane`，确认失败。**
- [ ] **Step 3: 实现 execute 用例，只消费 preview manifest，不重新解析原始格式；执行时创建 import task，并异步/后台推进 annotation 落库。**
- [ ] **Step 4: 让 task runner 产出 `start / phase / warning / error / complete` 事件，并记录最终 result。**
- [ ] **Step 5: 保持第一阶段语义为整批成功或整批失败，不做部分成功和补偿。**
- [ ] **Step 6: 重新运行 execute/task runner 测试并确认通过。**
- [ ] **Step 7: Commit。**

```bash
git add saki-controlplane/internal/modules/importing/app saki-controlplane/internal/modules/annotation/repo/annotation_repo.go saki-controlplane/internal/modules/annotation/app/create_annotation.go
git commit -m "feat(import): add execute task pipeline"
```

### Task 7: 将 import API 接入 `public-api` 并提供 SSE 事件流

**Files:**
- Modify: `saki-controlplane/api/openapi/public-api.yaml`
- Create: `saki-controlplane/internal/modules/importing/apihttp/handlers.go`
- Create: `saki-controlplane/internal/modules/importing/apihttp/handlers_test.go`
- Create: `saki-controlplane/internal/modules/importing/apihttp/sse.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/server.go`
- Modify: `saki-controlplane/internal/modules/system/apihttp/openapi_smoke_test.go`

- [ ] **Step 1: 为 import API 写失败测试，覆盖以下路径：`POST /imports/uploads:init`、`POST /imports/uploads/{session_id}/parts:sign`、`POST /imports/uploads/{session_id}:complete`、`POST /imports/uploads/{session_id}:abort`、`GET /imports/uploads/{session_id}`、`POST /projects/{project_id}/imports/annotations:prepare`、`POST /projects/{project_id}/imports/annotations:execute`、`GET /imports/tasks/{task_id}`、`GET /imports/tasks/{task_id}/result`、`GET /imports/tasks/{task_id}/events`。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make gen-openapi && PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./internal/modules/importing/apihttp ./internal/modules/system/apihttp -v` 于 `saki-controlplane`，确认失败。**
- [ ] **Step 3: 在 `public-api.yaml` 中补 import schemas 与路径，保持 `prepare / execute / task / events` 的长期交互模型。**
- [ ] **Step 4: 实现 apihttp handlers 和 SSE 事件流，`prepare` 返回 preview result，`execute` 返回 task create 响应，task events 用 `text/event-stream`。**
- [ ] **Step 5: 在 `server.go` 中装配 importing handlers，并把 import 路径加入 smoke 测试。**
- [ ] **Step 6: 重新运行 `make gen-openapi`、import api 测试与 smoke 测试并确认通过。**
- [ ] **Step 7: Commit。**

```bash
git add saki-controlplane/api/openapi/public-api.yaml saki-controlplane/internal/modules/importing/apihttp saki-controlplane/internal/modules/system/apihttp
git commit -m "feat(import): add public api endpoints"
```

## Chunk 5: 最终验证与执行基线

### Task 8: 做全量回归验证并固定新的 import 基线

**Files:**
- Modify: `saki-controlplane/Makefile`
- Modify: `saki-controlplane/.github/workflows/controlplane-ci.yml`
- Modify: `docs/superpowers/specs/2026-03-16-saki-import-go-native-adapters-design.md` (仅当实现与 spec 细节有必要同步时)

- [ ] **Step 1: 如有必要，在 `Makefile` 中补导入相关的文档化命令，但不要引入与现有 CI 重复的杂项目标。**
- [ ] **Step 2: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./...` 于 `shared/saki-ir/go`。**
- [ ] **Step 3: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make check-gen` 于 `saki-controlplane`。**
- [ ] **Step 4: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go test ./... && PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" go vet ./...` 于 `saki-controlplane`。**
- [ ] **Step 5: 运行 `PATH="$HOME/.local/bin:$HOME/go/bin:$PATH" make smoke-public-api` 于 `saki-controlplane`。**
- [ ] **Step 6: 确认当前阶段没有引入新的 Python import 依赖或常驻 Python import worker。**
- [ ] **Step 7: Commit。**

```bash
git add saki-controlplane/Makefile saki-controlplane/.github/workflows/controlplane-ci.yml docs/superpowers/specs/2026-03-16-saki-import-go-native-adapters-design.md
git commit -m "chore(import): add import verification baseline"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-16-saki-import-go-native-adapters.md`. Ready to execute?
