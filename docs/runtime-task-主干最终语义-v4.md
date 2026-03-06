# Runtime Task 主干最终语义 v4

> 生效日期：2026-03-06  
> 状态：当前唯一生效文档（Hard Cut）  
> 废弃：`runtime-unified-semantics-hardcut-v3.md`、`runtime-loop-round-step-语义计划书-v2.md`

## 1. 摘要

1. `Loop / Round / Step` 仅保留编排语义，执行真相源统一为 `Task`。  
2. `Prediction` 为循环外独立资源，不再挂靠 loop/round/step。  
3. 执行绑定固定为 1:1：`step.task_id -> task.id`、`prediction.task_id -> task.id`。  
4. 运行时协议、派发、事件、指标、候选、结果均使用 `task_id` 主干。  
5. 本版为硬切语义，不提供 `prediction_set`、`step_type=PREDICT`、`/steps/{step_id}/events` 兼容层。  

## 2. 统一资源模型

1. `step`：编排节点，保留 `step_type`、`depends_on_step_ids`、`step_index`。  
2. `task`：执行实体，保留 `kind`、`task_type`、`status`、`attempt/max_attempts`、`resolved_params`、`depends_on_task_ids`。  
3. `prediction`：预测任务资源，保留模型来源、目标分支、作用域、业务状态；执行状态来自 `task_status`。  
4. `task_event / task_metric_point / task_candidate_item / dispatch_outbox`：统一执行观测与派发持久化。  

## 3. 编排与派发

1. Dispatcher 只从 task 队列派发（单入口）。  
2. 内部可按 `task.kind` 分支执行：`STEP`（带 step 投影）与 `PREDICTION`（独立 task）。  
3. Step 相关状态推进会同步写 task；task 事件/结果落库后再写 step/round 投影。  
4. 缺失 step-task 投影属于数据错误，派发侧直接失败并记录错误，避免空转。  

## 4. API 与协议

1. Prediction 创建请求体仅支持：`model_id`、`artifact_name`、`target_branch_id`、`base_commit_id`、`predict_conf`、`scope_type/scope_payload`、`params`。  
2. 任务事件接口：`/tasks/{task_id}/events`、`/tasks/{task_id}/events/ws`。  
3. Round 事件接口：`/rounds/{round_id}/events`、`/rounds/{round_id}/events/ws`，事件主键为 `task_id + seq`。  
4. `step_id` 仅作为 round 视图辅助字段（排序/跳转），不是事件主键。  

## 5. 前端约束

1. Round 控制台按 `taskId` 聚合多 task 日志。  
2. Prediction 页面按单 `taskId` 展示日志与状态。  
3. `PredictionSet` 命名与旧入口文案全部淘汰，统一为 `Prediction` / `Prediction Task`。  

## 6. 测试与回归基线

1. `saki-dispatcher`: `go test ./...`。  
2. `saki-api`: runtime 契约与 task 主干回归用例必须通过。  
3. `saki-web`: `npm run -s build` 必须通过。  
4. 依赖 Redis/MinIO 的测试属于环境项，不影响 task 主干语义判定。  
