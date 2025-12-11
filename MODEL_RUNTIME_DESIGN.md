# Model Runtime 设计文档（扩展版，Runtime 拉取 Saki IR，适合 Copilot 不跑偏）

> 版本：v0.2（HTTP + WS；按 gRPC 的契约风格）
> 范围：检测任务为第一阶段（后续分割可扩展）
> 你选择的对接方式：**Model Runtime 主动调用 Saki API 拉取 IR（样本/标注/标签/版本信息）**
> 目标读者：人类开发者 + Copilot/AI（避免实现跑偏）

---

## 0. 强约束与设计哲学（AI 必读）

### 0.1 单一职责（必须遵守）

* **Saki API 是“事实源（Source of Truth）”**：项目/数据集/标注/版本关系都以 Saki 为准。
* **Runtime 是“执行器（Executor）”**：训练/推理/选样/产出制品与事件，不写业务 DB。

### 0.2 任何持久化都写在 Runtime 的 run 目录（必须）

* Runtime 的任务状态、事件流、制品，都以 `runs/{job_id}/...` 为主。
* Runtime **不允许**把训练过程中产生的数据写回 Saki DB（除了通过 query 结果让 Saki 选择性入库）。

### 0.3 接口契约优先（必须）

* 所有 HTTP 请求/响应必须满足本文件的数据结构（字段名、枚举、错误码）。
* 允许新增字段，但不得破坏既有字段语义。
* 所有状态迁移必须遵循状态机（见第 4 章）。

### 0.4 “小而强”的 MVP 边界（必须）

* 先实现 `train_detection` + `query(image)`；不做多机、不做复杂权限、不做容器插件。
* 训练脚本必须通过 SDK 上报结构化事件，不允许只 print。

---

## 1. 组件与依赖（建议落地）

### 1.1 Runtime 技术栈建议（MVP）

* Python 3.10+
* FastAPI（HTTP 控制面）+ WebSocket（事件流）
* Pydantic v2（强类型契约）
* httpx（Runtime 调 Saki API）
* 子进程：subprocess（训练/推理隔离）
* 文件锁：portalocker 或 fasteners（GPU 资源锁）
* 存储：本地文件（URI 使用 `file://`；未来可扩展 MinIO）

> 不引入 Redis/Kafka：事件先落盘 jsonl + tail 推送即可。

---

## 2. 目录与模块（仅包括代码结构，可以进一步更改）

```
  main.py                       # FastAPI 入口
  api/
    deps.py                    # 依赖注入（config、saki client、job manager）
    endpoints/
      plugins.py
      jobs.py
      query.py
      stream.py           # WS
      health.py
  core/
    config.py                  # 环境变量、路径、token
    errors.py                  # 统一错误码与异常
    models.py                  # Pydantic：请求/响应/IR/事件/枚举
    saki_client.py             # 调用 Saki IR 的客户端（httpx）
    plugin_registry.py         # 插件加载（plugins.yaml）
    artifact_store.py          # 本地制品存储（URI）
    event_store.py             # events.jsonl 写入/读取/tail
    locks.py                   # GPU 锁
  jobs/
    job_state.py               # JobState 状态机
    job_manager.py             # create/start/stop/get/metrics/artifacts
    runner.py                  # subprocess 启动/停止/监控
    workspace.py               # workdir 结构：runs/{job_id}
  plugins/
    base.py                    # 插件抽象类（Schema/Adapter/Trainer/Scorer）
    builtin/
      yolo_det_v1/
        plugin.py              # Plugin 实现
        adapter.py             # IR -> 训练格式
        train_entry.py         # 子进程训练入口
        infer_entry.py         # 子进程推理/打分入口
        schema_train.json      # 训练 schema
        schema_query.json      # query schema
  sdk/
    reporter.py                # 子进程上报事件（写 events.jsonl）
```

---

## 3. IR 数据契约（Runtime 从 Saki 拉取的内容）

> Saki API 必须提供稳定 IR；Runtime 只消费，不解释业务含义。

### 3.1 IR：Sample

```json
{
  "id": "sample_123",
  "uri": "file:///abs/path/to/sample_123.png",
  "width": 1024,
  "height": 512,
  "meta": {
    "dataset_version_id": "dv_10",
    "preprocess": {"log": true, "norm": "minmax", "colormap": "viridis"}
  }
}
```

### 3.2 IR：Label

```json
{"id": 3, "name": "vertical_stripe", "color": "#ffcc00"}
```

### 3.3 IR：Detection Annotation

```json
{
  "id": "ann_999",
  "sample_id": "sample_123",
  "category_id": 3,
  "bbox_xywh": [120.5, 80.0, 60.0, 200.0],
  "obb": null,
  "source": "human",
  "confidence": null
}
```

### 3.4 IR 拉取最小集合

* 样本列表（含 uri）
* 标注列表（仅已标注样本）
* 标签列表（类别表）
* 版本元信息（dataset_version / label_version 的创建时间、数量摘要等，可选但建议）

---

## 4. Job 状态机（不可违反）

### 4.1 枚举

```text
JobStatus = created | queued | running | stopping | stopped | succeeded | failed
```

### 4.2 允许的迁移

* created → queued → running
* running → stopping → stopped
* running → succeeded
* running → failed
* queued → stopped（取消）
* created → stopped（取消）

### 4.3 禁止行为（AI 必读）

* 终态（stopped/succeeded/failed）**禁止**再次 start
* stop 只对 running 有意义；对终态 stop 必须返回 200 + 当前状态（幂等）

---

## 5. 事件协议（Event Protocol，强类型）

### 5.1 Envelope（统一格式）

```json
{
  "job_id": "job_abc",
  "seq": 128,
  "ts": 1730000000,
  "type": "metric",
  "payload": {}
}
```

### 5.2 type 枚举与 payload

* log: `{level, message}`
* progress: `{epoch, step, total_steps, eta_sec}`
* metric: `{step, metrics:{...}}`
* artifact: `{kind, name, uri, meta?}`
* status: `{status, reason?}`

### 5.3 落盘规范（强制）

* 文件：`runs/{job_id}/events.jsonl`
* 每行一个 JSON envelope（严格 JSON，不允许多行）
* seq 从 1 递增，断点续传依赖 seq

---

## 6. Runtime API（HTTP 控制面 + WS）

> 所有 API 以 `/v1` 前缀。
> Runtime 对外只给 Saki API 调用（推荐），前端不直连 Runtime。

### 6.1 插件

#### GET /v1/plugins

返回可用插件列表。

#### GET /v1/plugins/{plugin_id}/schema?op=train|query|infer

返回 JSON Schema（带 ui hints），用于 Saki 前端动态表单。

#### GET /v1/plugins/{plugin_id}/capabilities

返回能力声明（task_types、unit 支持等）。

---

### 6.2 Job

#### POST /v1/jobs

创建 job（仅创建，不自动启动）。

请求（强制字段）：

```json
{
  "job_type":"train_detection",
  "project_id":"proj_1",
  "plugin_id":"yolo_det_v1",
  "data_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
  "params":{...},
  "resources":{"gpu":{"count":1,"device_ids":[0]},"cpu":{"workers":4}}
}
```

响应：

```json
{"request_id":"req_x","job_id":"job_abc","status":"created"}
```

校验规则（必须）：

* plugin_id 必须存在
* job_type 必须被 plugin capabilities 支持
* params 必须通过 schema 校验，否则 422
* resources 校验：MVP 只允许 `count=1` 且 `device_ids` 长度 1

---

#### POST /v1/jobs/{job_id}:start

* 幂等：若已 running，返回当前状态

#### POST /v1/jobs/{job_id}:stop

* 幂等：若已终态，返回当前状态

#### GET /v1/jobs/{job_id}

返回 job 全量信息（包含 summary.latest_metrics/progress）。

#### GET /v1/jobs/{job_id}/metrics

从 events.jsonl 聚合或从 metrics.jsonl 读取（实现任选其一，但输出结构必须一致）。

#### GET /v1/jobs/{job_id}/artifacts

列出制品（至少包含 config.json、events.jsonl、best.pt 若有）。

---

### 6.3 事件流

#### WS /v1/jobs/{job_id}/stream

* 客户端可发：`{"type":"subscribe","since_seq":0}`
* 服务端推：Event Envelope
* 断线重连：带 since_seq 补发（实现必须支持）

---

### 6.4 主动学习选样

#### POST /v1/query

请求：

```json
{
  "project_id":"proj_1",
  "plugin_id":"yolo_det_v1",
  "model_ref":{"job_id":"job_abc","artifact_name":"best.pt"},
  "unlabeled_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
  "unit":"image",
  "strategy":"uncertainty",
  "topk":200,
  "params":{"score_method":"1-max_conf","min_conf":0.05,"max_images":5000}
}
```

响应：

```json
{
  "request_id":"req_x",
  "candidates":[
    {"sample_id":"sample_9","score":0.83,"reason":{"max_conf":0.17}}
  ]
}
```

约束（必须）：

* candidates 按 score 降序
* topk 若超出可用样本数，则返回全部
* score 归一化范围建议 `[0,1]`（不强制，但推荐）
* Runtime 不负责入库 selection batch；由 Saki 接收到 candidates 后入库

---

## 7. Runtime 调用 Saki IR：Saki 内部 API 规范（你需要在 Saki 实现）

> Runtime 拉 IR 必须“可版本化、可分页、可过滤、可复现”。

### 7.1 鉴权（内部调用）

Saki 提供内部 token 方式：

* Runtime 请求头：`X-Internal-Token: <token>`
* Saki 校验 token（环境变量配置）

### 7.2 必须提供的 endpoints（建议以 /internal/v1 开头）

#### 7.2.1 获取项目标签（类别表）

`GET /internal/v1/projects/{project_id}/labels`

响应：

```json
{"labels":[{"id":1,"name":"..."}]}
```

#### 7.2.2 获取样本列表（按 dataset_version）

`GET /internal/v1/dataset-versions/{dv}/samples?limit=1000&cursor=...`

响应：

```json
{
  "dataset_version_id":"dv_10",
  "items":[{SampleIR},{SampleIR}],
  "next_cursor":"..."
}
```

强制要求：

* 返回稳定排序（例如按 sample_id）
* 支持分页 cursor（避免一次拉爆内存）
* SampleIR 必须包含 `uri,width,height`

#### 7.2.3 获取标注列表（按 label_version）

`GET /internal/v1/label-versions/{lv}/annotations?task_type=detection&limit=1000&cursor=...`

响应：

```json
{
  "label_version_id":"lv_7",
  "task_type":"detection",
  "items":[{AnnotationIR},{AnnotationIR}],
  "next_cursor":"..."
}
```

#### 7.2.4 获取“未标注样本集合”（用于 query）

为了避免 Runtime 自己做 set difference（样本量大时慢），建议 Saki 提供：

`GET /internal/v1/dataset-versions/{dv}/unlabeled-samples?label_version_id={lv}&limit=1000&cursor=...`

响应同 samples。

> 若你暂时不实现这个接口，Runtime 可以自己做差集：`all_samples - annotated_sample_ids`，但请在实现里加缓存并注意内存。

#### 7.2.5 获取版本元信息（可选但强烈建议）

`GET /internal/v1/dataset-versions/{dv}`
`GET /internal/v1/label-versions/{lv}`

用于记录 run 的可复现快照（样本数、创建时间、预处理参数等）。

---

## 8. 训练/推理执行规范（Copilot 不跑偏的关键）

### 8.1 Workspace 目录规范（强制）

创建 job 时必须创建：

```
runs/{job_id}/
  config.json              # job 快照（params、data_ref、plugin版本、resources）
  events.jsonl             # 事件流
  artifacts/
  cache/                   # adapter 缓存、下载缓存（未来 minio）
  data/                    # adapter 生成的数据集（如 yolo 格式）
```

### 8.2 config.json 内容（强制字段）

```json
{
  "job_id":"job_abc",
  "job_type":"train_detection",
  "plugin_id":"yolo_det_v1",
  "plugin_version":"0.1.0",
  "project_id":"proj_1",
  "data_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
  "params":{...},
  "resources":{...},
  "created_at":1730000000
}
```

### 8.3 Runner：子进程启动参数规范（强制）

Runtime 启动训练子进程时必须传：

* `--job-id job_abc`
* `--workdir runs/job_abc`
* `--config runs/job_abc/config.json`
* `--data-dir runs/job_abc/data`
* `--artifacts-dir runs/job_abc/artifacts`
* `--events runs/job_abc/events.jsonl`

同理推理/打分入口也遵循相同约定。

### 8.4 SDK 上报（强制）

子进程不得直接操作 WS；只做：

* `report_log(level, msg)`
* `report_progress(epoch, step, total_steps, eta)`
* `report_metric(step, metrics_dict)`
* `report_artifact(kind, name, uri, meta)`
* `report_status(status, reason)`

SDK 实现：将 event envelope append 到 `events.jsonl`，并维护 seq 自增（可用文件锁防并发，或单进程写即可）。

---

## 9. DataAdapter 规范（IR → 训练框架）

> Adapter 的职责是“把 Saki IR 变成训练可用数据”，不做训练逻辑。

### 9.1 Adapter 输入（强制）

* project_id
* dataset_version_id
* label_version_id
* labels（类别表）
* samples（分页拉取）
* annotations（分页拉取）
* workdir/data 目标目录

### 9.2 Adapter 输出（必须）

* 生成 `runs/{job_id}/data/` 下的训练数据布局
* 同时写一个 `dataset_manifest.json`（强制）

  * 包含样本数量、标注数量、类别映射、生成时间、来源版本、用于复现

示例 manifest：

```json
{
  "task_type":"detection",
  "format":"yolo",
  "dataset_version_id":"dv_10",
  "label_version_id":"lv_7",
  "num_samples":5000,
  "num_labeled_samples":200,
  "num_annotations":1200,
  "labels":[{"id":1,"name":"..."}]
}
```

### 9.3 Adapter 性能约束（建议）

* 图片不复制：优先软链接（symlink）或写路径索引（取决于训练框架）
* 标注文件可生成在本地（txt/json），这部分体积小
* 分页拉取：避免一次性加载全部 annotations 到内存（可按 sample_id 分桶或先写临时索引）

---

## 10. Query（主动学习选样）内部流程（必须按此实现）

> Runtime 的 query 不是“随便挑”，必须可复现、可解释、可扩展。

### 10.1 Query 步骤（强制顺序）

1. 校验 plugin 与 params schema（op=query）
2. 加载 model_ref（从 job artifacts 找到 best.pt）
3. 从 Saki 拉取未标注样本列表（优先用 `unlabeled-samples` 接口）
4. 对样本进行推理（可限量 max_images）
5. 为每个样本计算 uncertainty 分数（MVP：1 - max_conf）
6. 排序取 topK，返回 candidates
7. 记录一份 query 快照到 `runs/{job_id_or_query_id}/query.json`（强烈建议）

### 10.2 不确定性分数（MVP 标准定义，避免实现歧义）

* 推理输出一组框，每个框有置信度 conf（0~1）
* 对单张图像：

  * 若无框：`max_conf = 0.0`，则 `score = 1.0`（模型“完全没把握/可能漏检”）
  * 否则 `max_conf = max(conf_i)`，`score = 1 - max_conf`
* 可选过滤：忽略 conf < min_conf 的框

返回 reason：

```json
{"max_conf":0.17,"num_boxes":4}
```

> 这一定义简单、可复现、对论文也好解释。

---

## 11. 错误处理与超时（AI 必读）

### 11.1 Runtime 调 Saki 的超时与重试

* 拉 IR：使用 httpx timeout（比如 30s）+ 最多 3 次重试（指数退避）
* 若 Saki 暂时不可用：

  * 训练 start 应失败并进入 failed（同时写 status event + reason）
  * query 应返回 503

### 11.2 作业失败的最小产物（强制）

当 job failed：

* events.jsonl 必须包含最终 status=failed
* config.json 必须存在
* artifacts 可以为空，但建议至少保存 `error.txt`

---

## 12. 时序（训练一轮 + query 一轮）——按这个对接不会跑偏

### 12.1 训练时序

1. 前端：填写 params → 提交到 Saki
2. Saki：`POST Runtime /jobs`（创建 job）
3. Saki：`POST Runtime /jobs/{id}:start`
4. Runtime：

   * 创建 workdir & config.json
   * Adapter：调用 Saki internal 拉取 labels/samples/annotations，生成 data/
   * Runner：启动 train_entry 子进程
5. Runtime：WS stream 持续输出 events
6. Saki：订阅 WS（或转发给前端），并同步 job 状态到自身 DB（可选）
7. 训练完成：产出 artifact best.pt + metrics；status succeeded

### 12.2 Query 时序

1. 前端：点击“主动学习选样 topK”
2. Saki：`POST Runtime /query`
3. Runtime：

   * 拉 unlabeled samples
   * 推理打分
   * 返回 candidates
4. Saki：把 candidates 入库为 SelectionBatch/Queue
5. 前端：显示优先标注队列

---

## 13. 最小安全策略（内部可信调用）

### 13.1 Runtime 接口鉴权（建议）

Runtime 仅接受 Saki：

* Header：`X-Internal-Token`
* Runtime 校验 token，不通过 403

### 13.2 Saki 内部接口鉴权（必须）

Saki internal endpoints 必须校验 `X-Internal-Token`

---

## 14. 给 Copilot/AI 的“实现禁区”（非常关键）

1. **不要让 Runtime 直接访问 Saki 数据库**：只能走 HTTP internal API
2. **不要把训练过程指标塞进 Saki DB**：先落盘 events.jsonl，Saki 只读展示/抽样入库
3. **不要省略 schema 校验**：create job / query 都必须做 schema 校验
4. **不要让子进程直接写 artifacts URI 为相对路径**：必须生成 `file:///abs/...`
5. **不要让 WS 直接读 stdout**：必须以 events.jsonl 为准（stdout 可辅助，但不是契约）
6. **不要在 Runtime 中实现项目/用户 CRUD**：那是 Saki 的职责

---

## 附录 A：Pydantic 模型清单（建议你直接照此建模）

> 下面是“类型名 + 关键字段”，建议你在 `core/models.py` 定义。

* `JobStatus(Enum)`

* `JobType(Enum)`：train_detection / score_unlabeled / export_model

* `EventType(Enum)`：log/progress/metric/artifact/status

* `SampleIR`

* `LabelIR`

* `DetAnnotationIR`

* `JobResources`：gpu/cpu/memory

* `JobDataRef`：dataset_version_id/label_version_id

* `JobCreateRequest`

* `JobCreateResponse`

* `JobInfo`（含 summary）

* `JobGetResponse`

* `MetricsResponse`

* `ArtifactsResponse`

* `ModelRef`：job_id + artifact_name

* `QueryRequest`

* `QueryCandidate`

* `QueryResponse`

* `ErrorResponse`：code/message/details

---

## 附录 B：Saki internal API 的最小返回字段（防跑偏）

Saki 返回给 Runtime 的 IR 必须满足：

* SampleIR：`id, uri, width, height` 必须存在
* AnnotationIR：`sample_id, category_id, bbox_xywh` 必须存在
* Labels：`id, name` 必须存在
* 分页：必须提供 `next_cursor`（无则为 null/空）

---

## 附录 C：建议的“内置插件 yolo_det_v1”职责划分（防止实现混乱）

* `schema_train.json`：epochs/imgsz/batch/lr0/seed/augment…
* `adapter.py`：

  * 调 Saki 拉 IR
  * 生成 yolo 格式 data：images/labels、data.yaml
  * 写 dataset_manifest.json
* `train_entry.py`（子进程）：

  * 读取 config/params
  * 调用 YOLO 训练
  * 用 SDK 写 events：progress/metric/artifact/status
* `infer_entry.py`（子进程）：

  * 加载 best.pt
  * 对输入 samples 推理，输出 per-sample score
  * 通过 stdout 输出 JSON（可），但最终仍建议通过文件写结果 + Runtime 读取

# Model Runtime 设计文档（HTTP 版，按 gRPC 思路组织契约）

> 目标：为你的 **Saki API（业务后端）** 提供一个独立的 **Model Runtime（模型运行时）** 服务，用于训练/推理/主动学习选样/产生日志指标/产出模型制品。
> 原则：**强契约**（像 gRPC 一样明确的 Request/Response/状态机/错误码）、**可插拔**（插件化）、**可复现**（版本与配置快照）、**可演示**（日志/曲线流式展示）。
> 协议：控制面 **HTTP/JSON**，事件流 **WebSocket（或 SSE）**。

---

## 0. 名词与角色

### 0.1 服务角色

* **Saki API（FastAPI）**：项目/数据集/标注/用户/权限/版本管理；负责与前端交互；负责把数据以 IR 形式提供给 Runtime。
* **Model Runtime（本设计文档的对象）**：加载插件并执行训练/推理/选样；管理 Job；生成日志/指标/制品；对外提供统一 API。
* **Worker（训练/推理进程）**：由 Runtime 启动的子进程（subprocess/multiprocessing），实际跑深度学习任务。

### 0.2 核心对象

* **Plugin（插件）**：可插拔的“任务实现体”（检测训练器/推理器/选样策略/数据适配器）。
* **Job（任务）**：一次训练或一次推理/打分运行的生命周期对象。
* **Artifact（制品）**：权重、配置、评估报告、推理缓存等可下载对象。
* **Event（事件）**：日志、进度、指标、状态变更、制品产生等结构化消息。

---

## 1. 总体架构与职责边界

### 1.1 Runtime 必须实现的能力（MVP）

1. 插件发现与参数 Schema 下发
2. 训练任务：创建 / 启动 / 停止 / 查询状态
3. 训练过程：日志与指标流式输出（WS）
4. 模型制品：保存、列举、可下载（通过 URI）
5. 主动学习选样：对未标注数据打分，返回 topK（图像级或 ROI 级）

### 1.2 不在 Runtime 内实现（由 Saki API 管）

* 用户体系与权限策略（Runtime 只做最小鉴权：信任上游或校验内部 token）
* 项目/数据集/标注 CRUD
* 标注编辑与审核流程
* 多租户配额/复杂任务调度（毕设阶段可做简化）

---

## 2. 数据契约（IR 中间表示）

> 设计目标：Runtime 不绑定某个训练框架；由插件的 DataAdapter 负责 IR → 训练框架格式转换。
> Saki API 必须能按版本提供“稳定的 IR”。

### 2.1 Sample（样本）

```json
{
  "id": "sample_123",
  "uri": "file:///abs/path/to/sample_123.png",
  "width": 1024,
  "height": 512,
  "meta": {
    "source": "MSS-1 FEDO",
    "time_range": ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"],
    "energy_bins": 128,
    "preprocess": {"log": true, "norm": "minmax", "colormap": "viridis"}
  }
}
```

### 2.2 Label（类别）

```json
{
  "id": 3,
  "name": "vertical_stripe",
  "color": "#ffcc00"
}
```

### 2.3 Detection Annotation（检测标注）

```json
{
  "id": "ann_999",
  "sample_id": "sample_123",
  "category_id": 3,
  "bbox_xywh": [120.5, 80.0, 60.0, 200.0],
  "obb": null,
  "source": "human",
  "confidence": null
}
```

> 说明：`obb` 可扩展为 `{cx,cy,w,h,angle}`。`source` 允许 human/model/weak 等。

### 2.4 DatasetRef / LabelRef（引用对象）

Runtime 不直接操作数据库，使用引用对象指向 Saki API 的版本资源：

```json
{
  "project_id": "proj_1",
  "dataset_version_id": "dv_10",
  "label_version_id": "lv_7"
}
```

---

## 3. 插件体系（可插拔核心）

### 3.1 插件的组成（检测任务 MVP）

一个检测插件至少包含：

* **SchemaProvider**：返回训练/推理/选样所需参数的 JSON Schema
* **DataAdapter**：把 Saki API 提供的 IR（样本+标注）转换为训练框架输入
* **Trainer**：执行训练，产出 weights/metrics
* **Scorer**：对未标注数据推理并给出不确定性分数
* **QueryStrategy（可选）**：把 scorer 输出聚合成最终 topK（支持多样性时会用）

### 3.2 插件注册与发现（MVP）

Runtime 启动时读取 `plugins.yaml`：

```yaml
plugins:
  - id: yolo_det_v1
    name: YOLO Detector v1
    version: 0.1.0
    module: model_runtime.plugins.builtin.yolo_det.plugin:Plugin
    task_types: [detection]
```

> 后续扩展：Python entrypoints / 容器插件。此文档先按配置加载实现。

### 3.3 插件能力声明（Capabilities）

* 支持任务类型：detection（后续 seg/cls）
* 支持输入标注类型：bbox/obb
* 支持导出：onnx/torchscript（可选）
* 支持选样单位：image/roi
* 支持评估指标：map50、recall、custom_metric

---

## 4. Job（任务）模型与状态机

### 4.1 Job 类型

* `train_detection`：训练检测模型
* `score_unlabeled`：对未标注数据打分（可由 query 内部触发，也可显式建 job）
* `export_model`：导出（可选）

### 4.2 Job 状态机（强约束）

`created -> queued -> running -> {succeeded|failed|stopped}`
中间态：`stopping`

规则：

* `start` 只能作用于 `created/queued`
* `stop` 只能作用于 `running`
* `stopping` 超时后强制 kill 并进入 `stopped`
* `succeeded/failed/stopped` 为终态，不可再次 start（需要新建 job）

### 4.3 Job 资源声明（MVP 简化）

```json
{
  "gpu": {"count": 1, "device_ids": [0]},
  "cpu": {"workers": 4},
  "memory_mb": 8192
}
```

> MVP 可以仅支持 `device_ids` 单卡；以后支持队列化/多卡。

---

## 5. 事件协议（Event Protocol）

> Runtime 与前端/后端沟通训练过程必须结构化，避免“只打印字符串”。
> 事件以统一 Envelope 封装，便于流式推送与落盘复现。

### 5.1 Event Envelope

```json
{
  "job_id": "job_abc",
  "seq": 128,
  "ts": 1730000000,
  "type": "metric",
  "payload": {}
}
```

`type` 枚举：

* `log`
* `progress`
* `metric`
* `artifact`
* `status`

### 5.2 各类 payload

**log**

```json
{"level":"INFO","message":"epoch 1 started"}
```

**progress**

```json
{"epoch":1,"step":120,"total_steps":1000,"eta_sec":3600}
```

**metric**

```json
{"step":120,"metrics":{"loss":1.23,"map50":0.41,"recall":0.66}}
```

**artifact**

```json
{"kind":"weights","name":"best.pt","uri":"file:///.../best.pt","meta":{"score":"map50=0.41"}}
```

**status**

```json
{"status":"running","reason":null}
```

### 5.3 事件落盘格式（推荐 JSONL）

Runtime 将事件写入：

* `runs/{job_id}/events.jsonl`（一行一个 envelope）
* `runs/{job_id}/config.json`（参数快照）
* `runs/{job_id}/artifacts/`（权重等）

---

## 6. API 设计（HTTP 控制面 + WS 事件流）

> 统一约定：
>
> * `Content-Type: application/json`
> * 所有响应包含 `request_id`（便于排查）
> * 采用“像 gRPC 一样”的方法命名：用动词后缀 `:start`、`:stop` 模拟 RPC。

### 6.1 插件相关

#### 6.1.1 列出插件

`GET /v1/plugins`

响应：

```json
{
  "request_id":"req_x",
  "plugins":[
    {"id":"yolo_det_v1","name":"YOLO Detector v1","version":"0.1.0","task_types":["detection"]}
  ]
}
```

#### 6.1.2 获取插件 schema

`GET /v1/plugins/{plugin_id}/schema?op=train|query|infer`

响应（JSON Schema + UI hints）：

```json
{
  "request_id":"req_x",
  "plugin_id":"yolo_det_v1",
  "op":"train",
  "schema":{
    "type":"object",
    "properties":{
      "epochs":{"type":"integer","default":50,"minimum":1,"ui:widget":"number"},
      "imgsz":{"type":"integer","default":640,"enum":[512,640,768],"ui:widget":"select"},
      "batch":{"type":"integer","default":16,"minimum":1},
      "lr0":{"type":"number","default":0.01,"minimum":1e-6},
      "seed":{"type":"integer","default":42}
    },
    "required":["epochs","imgsz","batch"]
  }
}
```

#### 6.1.3 获取能力声明

`GET /v1/plugins/{plugin_id}/capabilities`

---

### 6.2 Job 生命周期

#### 6.2.1 创建 Job

`POST /v1/jobs`

请求：

```json
{
  "job_type":"train_detection",
  "project_id":"proj_1",
  "plugin_id":"yolo_det_v1",
  "data_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
  "params":{"epochs":50,"imgsz":640,"batch":16,"lr0":0.01,"seed":42},
  "resources":{"gpu":{"count":1,"device_ids":[0]},"cpu":{"workers":4}}
}
```

响应：

```json
{"request_id":"req_x","job_id":"job_abc","status":"created"}
```

> 约束：Runtime 必须在创建时做 `params` 校验（schema），不通过返回 422。

#### 6.2.2 启动 Job

`POST /v1/jobs/{job_id}:start`

响应：

```json
{"request_id":"req_x","job_id":"job_abc","status":"running"}
```

#### 6.2.3 停止 Job

`POST /v1/jobs/{job_id}:stop`

响应：

```json
{"request_id":"req_x","job_id":"job_abc","status":"stopping"}
```

#### 6.2.4 查询 Job

`GET /v1/jobs/{job_id}`

响应：

```json
{
  "request_id":"req_x",
  "job":{
    "job_id":"job_abc",
    "job_type":"train_detection",
    "plugin_id":"yolo_det_v1",
    "status":"running",
    "created_at":1730000000,
    "started_at":1730000100,
    "ended_at":null,
    "data_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
    "params":{"epochs":50,"imgsz":640,"batch":16,"lr0":0.01,"seed":42},
    "resources":{"gpu":{"count":1,"device_ids":[0]}},
    "summary":{"latest_metrics":{"map50":0.41,"loss":1.12},"progress":{"epoch":3,"step":120}}
  }
}
```

#### 6.2.5 拉取 metrics（非实时）

`GET /v1/jobs/{job_id}/metrics?from_step=0&limit=2000`

响应：

```json
{
  "request_id":"req_x",
  "series":[
    {"step":10,"metrics":{"loss":2.1}},
    {"step":20,"metrics":{"loss":1.9}}
  ]
}
```

#### 6.2.6 列出 artifacts

`GET /v1/jobs/{job_id}/artifacts`

响应：

```json
{
  "request_id":"req_x",
  "artifacts":[
    {"kind":"weights","name":"best.pt","uri":"file:///.../best.pt"},
    {"kind":"config","name":"config.json","uri":"file:///.../config.json"}
  ]
}
```

---

### 6.3 事件流（实时日志/进度/指标）

#### 6.3.1 WebSocket 订阅

`WS /v1/jobs/{job_id}/stream`

服务器推送：Event Envelope（见第 5 章）。
客户端可选发送：

```json
{"type":"subscribe","since_seq":0}
```

> 实现建议：Runtime tail `events.jsonl` 并推送；断线重连用 `since_seq` 补发。

---

### 6.4 主动学习选样（Query）

`POST /v1/query`

请求：

```json
{
  "project_id":"proj_1",
  "plugin_id":"yolo_det_v1",
  "model_ref":{"job_id":"job_abc","artifact_name":"best.pt"},
  "unlabeled_ref":{"dataset_version_id":"dv_10","label_version_id":"lv_7"},
  "unit":"image",
  "strategy":"uncertainty",
  "topk":200,
  "params":{
    "score_method":"1-max_conf",
    "min_conf":0.05,
    "max_images":5000
  }
}
```

响应：

```json
{
  "request_id":"req_x",
  "candidates":[
    {"sample_id":"sample_9","score":0.83,"reason":{"max_conf":0.17}},
    {"sample_id":"sample_42","score":0.81,"reason":{"max_conf":0.19}}
  ]
}
```

> 扩展：`unit="roi"` 时返回 `roi` 字段（bbox/obb），用于 ROI 级标注队列。

---

## 7. Runtime 如何获取数据（与 Saki API 的数据对接）

Runtime 不直接读 Saki DB。推荐两种方式（二选一，MVP 建议 A）：

### A) Runtime 调 Saki API 拉 IR（推荐）

Saki API 提供：

* `GET /internal/datasets/{dv}/samples` → Sample 列表（含 uri）
* `GET /internal/labels/{lv}/annotations` → Annotation 列表
* `GET /internal/projects/{id}/labels` → 类别表

Runtime 在 `DataAdapter.prepare()` 阶段调用这些接口，生成训练所需文件。

优点：清晰解耦；缺点：需要内部鉴权 token。

### B) Saki API 预导出训练包，Runtime 只消费包

Saki API 生成一个 `export.zip`（COCO/YOLO），Runtime 解压训练。
优点：Runtime 更简单；缺点：导出逻辑会挤压 Saki API 职责。

---

## 8. 错误码与幂等性（按 gRPC 思路）

### 8.1 统一错误响应

```json
{
  "request_id":"req_x",
  "error":{
    "code":"INVALID_ARGUMENT",
    "message":"epochs must be >= 1",
    "details":{"field":"epochs"}
  }
}
```

### 8.2 HTTP 状态码映射

* 400：参数格式错误（JSON 解析失败）
* 401/403：鉴权失败（若启用）
* 404：资源不存在（job/plugin 不存在）
* 409：状态冲突（比如对终态 job start）
* 422：schema 校验失败（字段缺失/范围不合法）
* 500：内部错误
* 503：资源不可用（GPU 忙、队列满）

### 8.3 幂等性

* `POST /jobs/{id}:start`：如果已 running，返回 200 + 当前状态（不要重复启动）
* `POST /jobs/{id}:stop`：如果已 stopped/failed/succeeded，返回 200 + 当前终态

---

## 9. 制品与存储（本地优先，MinIO 可扩展）

### 9.1 URI 统一规范

* 本地：`file:///abs/path/...`
* 未来 MinIO：`s3://bucket/key`

Runtime 对外只暴露 `uri`。如需下载：

* 可选提供：`GET /v1/artifacts/download?uri=...`（本地实现）
* 或由 Saki API 代理下载（推荐统一入口）

### 9.2 目录约定

```
runs/{job_id}/
  config.json
  events.jsonl
  artifacts/
    weights/best.pt
    weights/last.pt
    reports/eval.json
```

---

## 10. 任务执行实现建议（MVP）

### 10.1 训练子进程约定

Runtime 启动训练时传入：

* job_id
* workdir
* params.json 路径
* data_dir（adapter 准备好的数据）
* output_dir

训练脚本通过 SDK 上报事件（写 events.jsonl 或 stdout 统一解析均可）。

### 10.2 停止机制

* SIGTERM → 等待 N 秒 → SIGKILL
* 停止时尽量保存 `last.pt`

### 10.3 资源锁

* 单机 GPU：用文件锁 `locks/gpu0.lock`
* 失败时释放锁（finally）

---

## 11. 安全与隔离（毕设阶段最小实现）

* Runtime 只接受来自 Saki API 的内部请求：

  * 使用简单的 `X-Internal-Token`（配置在环境变量）
* 插件执行为“可信代码”（毕设阶段默认可信）
* 日后扩展：容器化 worker 隔离依赖与权限

---

## 12. 版本与可复现要求（强建议必须做）

每个 train job 必须保存：

* `params`（最终生效配置）
* `data_ref`（dataset_version_id、label_version_id）
* `plugin_id` + `plugin_version`
* `seed`、imgsz、增强开关等关键超参
* （可选）git commit hash

这使得你论文实验可追溯，学习曲线可自动生成。

---

## 13. 面向“检测→分割”二阶段的扩展点（预留接口）

未来增加 segmentation 时：

* 新 job_type：`train_segmentation`
* query 可返回 ROI（检测框），生成 ROI patch 数据集版本
* IR 增加 mask/polygon 标注类型
* 插件能力声明增加 seg 支持

现阶段设计已兼容：通过 `job_type` 与 `capabilities` 扩展即可。

---

# 附录 A：推荐的最小实现顺序（你按这个做不容易走歪）

1. Event 模型 + events.jsonl 落盘 + WS tail 推送
2. JobManager（create/start/stop/status）+ 子进程 Runner
3. 插件加载（plugins.yaml）+ schema 下发
4. 内置一个检测插件（yolo_det_v1）：adapter→train→产出 best.pt+metrics
5. query：推理+不确定性 topK（image 级）
6. Saki API 对接：提供 IR 拉取接口 + 触发 Runtime + 前端展示曲线/队列

---

如果你希望我把这份文档进一步“压实到可编码级别”，我可以继续补两样东西（都很关键）：

1. **Pydantic 数据模型清单**（每个 request/response 的字段与类型、枚举）
2. **接口时序图**（训练一轮、query 一轮、标注回流一轮的完整调用链）
