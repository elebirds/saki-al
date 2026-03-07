# Runtime 统一语义硬切方案 v3（历史版）

> 生效日期：2026-03-01  
> 状态：已废弃（仅保留历史记录）  
> 当前生效文档：[`runtime-task-主干最终语义-v4.md`](./runtime-task-主干最终语义-v4.md)

## 1. 摘要

1. 保留 `snapshot`，并扩展为 AL + Sim 共用的全集/分区版本化能力。  
2. 新增循环外 `prediction_set` 资源，承担模型预测辅助标注流程，与 `snapshot` 职责分离。  
3. 三模式主轮统一为 4 阶段语义：`train -> eval -> score -> select`（Manual 仅执行前两步）。  
4. 默认编排删除：`activate_samples`、`advance_branch`、`export`、`upload_artifact`。  
5. 前端 Round 页采用“Round 主视图 + Step 时间线（轻量语义）”，控制台默认不筛阶段。  
6. 本次为硬切，不做兼容层，不保留旧接口语义。  

## 2. 统一语义定义

1. `Loop`：实验生命周期容器。  
2. `Round`：一次迭代执行上下文。  
3. `Step`：最小执行单元，保留 `step_id` 作为事件/指标/制品/日志/重试主键。  
4. `Snapshot`：静态版本化分区（全集、train_seed、train_pool、val/test 等）。  
5. `LoopSampleState`：动态可见性状态（每轮 reveal 后进入可训练集）。  
6. `PredictionSet`：循环外预测结果包，供人工修订并写回 draft/commit。  

## 3. 三模式执行模型

1. active_learning：`train -> eval -> score -> select`；允许手动调整 select；需 confirm；下一轮手动触发 `start_next_round`。  
2. simulation：`train -> eval -> score -> select`；不手动调整；`snapshot` 全集固定为 `oracle_commit` 的已标注样本子集（`CommitSampleState=LABELED/EMPTY_CONFIRMED`）；每轮自动 reveal 并自动下一轮，直到 `pool_hidden==0`。  
3. manual：`train -> eval`；无 select；支持手动 `start_next_round`。  

## 4. Snapshot 与 PredictionSet 关系

1. `snapshot` 只负责样本集合与分区版本，不承载预测结果。  
2. `prediction_set` 只负责某模型在某范围样本上的预测产物。  
3. 二者通过 `base_commit_id` 与 `sample_scope` 关联，但生命周期独立。  
4. `prediction_set` apply 结果写入 working/draft，再由现有 draft commit 机制生成新 commit。  

## 5. 后端模型与契约

1. 快照表泛化为模式无关语义（表名建议 `loop_snapshot_version`、`loop_snapshot_sample`）。  
2. 新增 `loop_sample_state`：`loop_id`、`sample_id`、`visible_in_train`、`revealed_round_index`、`reveal_commit_id`、`source`、`created_at`、`updated_at`。  
3. 新增 `prediction_set`：`id`、`loop_id`、`source_round_id`、`source_step_id`、`model_id`、`base_commit_id`、`scope_type`、`scope_payload`、`status`、`total_items`、`params`、`created_by`、`created_at`、`updated_at`。  
4. 新增 `prediction_item`：`prediction_set_id`、`sample_id`、`rank`、`score`、`label_id`、`geometry`、`attrs`、`confidence`、`meta`。  
5. `round_selection_override` 泛化为 Round 通用（写权限继续受模式约束）。  

## 6. 枚举与状态机

1. `StepType` 删除：`ACTIVATE_SAMPLES`、`ADVANCE_BRANCH`、`EXPORT`、`UPLOAD_ARTIFACT`。  
2. `StepType` 新增：`PREDICT`（仅 prediction_set 执行，不进入主轮默认 plan）。  
3. `LoopPhase` 删除：`SIM_ACTIVATE`、`MANUAL_EXPORT`。  
4. `confirm` 保持动作为 gate 触发，不新增 confirm 阶段。  
5. `wait_user` 与 `next_round` 分离：前者是 gate，后者是动作。  

## 7. Dispatcher/Runtime 编排要求

1. AL 步骤顺序：`TRAIN -> EVAL -> SCORE -> SELECT`。  
2. Sim 步骤顺序：`TRAIN -> EVAL -> SCORE -> SELECT`。  
3. Manual 步骤顺序：`TRAIN -> EVAL`。  
4. Sim 每轮 `round.input_commit_id` 与 `step.input_commit_id` 固定为 `config.mode.oracle_commit_id`，不跟随 branch head。  
5. Sim 终止规则：`pool_hidden_after==0` 视为成功完成；`revealed_count==0 && pool_hidden_after>0` 视为失败；`max_rounds` 仅作为保险丝。  
6. 删除 orchestrator 对 `ACTIVATE_SAMPLES/ADVANCE_BRANCH` 执行分支。  
7. `StartNextRound` 支持 Manual。  
8. `ConfirmLoop`：Sim 恒拒绝，Manual 恒拒绝。  

## 8. API 契约要求

1. 删除：`GET /loops/{loop_id}/label-readiness`。  
2. 删除：`POST /projects/{project_id}/simulation-experiments`、`GET /simulation-experiments/{group_id}/comparison`。  
3. 保留：`GET /loops/{loop_id}/snapshot`、`POST /loops/{loop_id}:act`。  
4. 新增：`POST /loops/{loop_id}/prediction-sets:generate`、`GET /loops/{loop_id}/prediction-sets`、`GET /prediction-sets/{prediction_set_id}`、`POST /prediction-sets/{prediction_set_id}:apply`。  
5. `GET /rounds/{round_id}/artifacts` 改为扁平聚合返回，字段固定：  
   `step_id`、`step_index`、`stage`、`artifact_class`、`name`、`kind`、`uri`、`size`、`created_at`。  
6. `GET /rounds/{round_id}/selection` 支持历史 round 只读查询。  
7. `POST /rounds/{round_id}/selection:apply/reset` 仅 AL 最新轮且未 confirm 可写。  

## 9. 前端要求（Round/Loop）

1. Round 顶部保留 Step 时间线，仅展示：`stepType`、`state`、`elapsedSec`。  
2. 点击时间线节点直接打开 Step 抽屉。  
3. 删除“打开 Step 详情”按钮。  
4. 删除“Round 阶段概览”区块。  
5. 阶段文案不再附带“（Round 聚合）”。  
6. 控制台默认 `all`（不筛阶段）。  
7. 点击时间线节点时，控制台切换到对应阶段。  
8. 制品统一单表展示，新增“来源阶段”与“类别”列。  
9. API 客户端统一依赖 `convertKeysToCamel`，删除命名差异专用 normalize 和结构兜底。  

## 10. 默认值

1. 不做兼容层。  
2. `step_id` 保留，不改为 `round_id + action` 复合键。  
3. Sim 默认 `auto_next_round=true`，且 reveal 数据源固定 `oracle_commit_id`。  
4. Manual 默认 `max_rounds=20`。  
5. PredictionSet apply 默认写入 working/draft，不直接落 commit。  
6. Snapshot 在 AL 与 Sim 均为必选启动条件。  
