# Runtime Loop 策略 V5.2（已废弃）

> 状态：历史文档（不再生效）  
> 替代文档：[`runtime-unified-semantics-hardcut-v3.md`](./runtime-unified-semantics-hardcut-v3.md)

## 1. 三层语义（唯一真值）

1. `lifecycle`：Loop 生命周期（持久化真值）。  
2. `phase`：执行指针（持久化真值）。  
3. `gate`：交互决策（实时计算，不持久化）。  

## 2. 统一动作入口

1. `POST /api/v1/loops/{loop_id}:act` 是 loop 生命周期动作唯一入口。  
2. `confirm` 为 reveal-only，不创建下一轮。  
3. `start_next_round` 单独负责进入下一轮。  
4. `continue` 在前端由 `primary_action` 驱动，不做前端硬编码推断。  

## 3. Gate 集合

1. `need_snapshot`
2. `need_labels`
3. `can_start`
4. `running`
5. `paused`
6. `stopping`
7. `need_round_labels`
8. `can_confirm`
9. `can_next_round`
10. `can_retry`
11. `completed`
12. `stopped`
13. `failed`

## 4. Label Readiness（替代 Annotation Gaps）

1. 旧术语 `Annotation Gaps` 已废弃。  
2. 新接口：`GET /api/v1/loops/{loop_id}/label-readiness`。  
3. `setup` 与 `current round` 统一为同一 checkpoint 模型：  
   - `round_index=0`：`seed / val_anchor / test_anchor`  
   - `round_index>=1`：`query`  
4. 响应主结构：
   - `checkpoints[]`
   - `active_checkpoint_id`
   - `commit_id`
5. 预览样本上限 50，避免响应膨胀。  

## 5. Snapshot 展示口径（业务短名）

`GET /api/v1/loops/{loop_id}/snapshot` 返回：

1. `primary_view`（主视图）  
   - `train`: 当前可训练集合（effective train）  
   - `pool`: 候选池（隐藏标签）  
   - `val`: 当前有效验证集  
   - `test`: Anchor Test（固定口径）  
2. `advanced_view`（高级视图）  
   - `bootstrap_seed`
   - `revealed_from_pool`
   - `pool_hidden`
   - `val_anchor / val_batch`
   - `test_anchor / test_batch / test_composite`
   - `manifest`

已删除旧字段：

1. `frozen_partition_counts`
2. `virtual_visibility_counts`
3. `effective_split_counts`

## 6. 判定优先级

`gate` 计算顺序固定：

1. 终态 lifecycle：`failed/completed/stopped`
2. 运行态 lifecycle：`running/paused/stopping`
3. 启动态 lifecycle：`draft`（仅此分支检查 `need_snapshot/need_labels`）

## 7. Confirm 阈值规则

1. `effective_min_required=min(configured_min_required, selected_count)`。  
2. 当 `selected_count=0`，`effective_min_required=0`。  
3. reveal/confirm 统一按 `round_id` 取候选，禁止按 `round_index` 混读 attempt。  

## 8. 废弃与硬切

1. `GET /api/v1/loops/{loop_id}/annotation-gaps` 已删除。  
2. 前端类型 `LoopAnnotationGapsResponse` 已删除。  
3. Loop action key `view_annotation_gaps` 已删除，改为 `view_label_readiness`。  
