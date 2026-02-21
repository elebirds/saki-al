# Dataset Snapshot & Manifest v1

## 1. 目标
1. 为主动学习与模拟轮次提供不可漂移的数据选择语义。
2. 通过 `snapshot_id + selector_bytes` 保证可重放、可恢复、可审计。

## 2. 核心表
1. `dataset_snapshot`
   - `id(uuidv7)`：快照主键
   - `dataset_id`
   - `parent_snapshot_id`
   - `universe_size(uint32)`
   - `max_ordinal(uint32)`
2. `dataset_snapshot_sample_ordinal`
   - `snapshot_id`
   - `sample_uuid`
   - `ordinal(uint32)`
   - `is_tombstone`
   - `tombstone_at`
   - `tombstone_reason`
3. `round_dataset_view`
   - 每轮每 split 的 selector 固化（`round_id + split` 唯一）
4. `al_session_state`
   - 会话恢复锚点：`snapshot_id + selector_bytes + cardinality + checksum`

## 3. 不变量
1. `unique(snapshot_id, sample_uuid)`。
2. `unique(snapshot_id, ordinal)`。
3. `ordinal` 不可更新（触发器拒绝）。
4. 新增样本 `ordinal` 必须为 `max(existing)+1`。
5. 删除仅 tombstone，不删除映射行、不复用 ordinal。

## 4. Selector 编码
1. `ROARING`：优先；`selector_bytes` 存 bitmap。
2. `RANGE`：连续区间回退；`selector_bytes` 为 `<start:uint32,end:uint32>` 小端序拼接。
3. `BITSET`：位图回退；`selector_bytes` 为 little-endian bytes。

## 5. 校验契约
1. `cardinality`：选择器样本数。
2. `checksum`：`sha256(snapshot_id + 0x00 + encoding_u32_le + selector_bytes + cardinality_u32_le)`。
3. Go/Python SDK 必须产出一致 `cardinality/checksum`。

## 6. 静态与动态 split
1. `val/test`：静态 split，在 loop 创建时一次锁定。
2. `train/unlabeled`：动态 split，通过 selector 边界移动。
3. simulation 模式：按轮次快照伪造可见 train/unlabeled。

## 7. Manifest 下发规则
1. 控制面到 Kernel 只下发 `dataset_manifest_ref + snapshot_id + selector`。
2. 禁止 API 返回海量文件名。
3. Kernel 通过 SDK 在工作区创建软链接，不移动原文件。
