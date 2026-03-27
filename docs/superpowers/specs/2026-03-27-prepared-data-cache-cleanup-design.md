# Prepared Data Cache 清理设计

日期：2026-03-27

## 1. 背景

`saki-executor` 会把训练任务 `prepare_data` 阶段生成的 `workspace.data_dir` 缓存在 `cache/prepared_data_v2/<fingerprint>` 下，用于后续相同训练输入的命中复用。

当前实现只有写入与恢复，没有容量上限、时间过期、索引自愈或启动清理机制。随着训练输入变化，fingerprint 会持续增加，目录大小单调增长，最终挤占 executor 的有限数据盘空间。

考虑到 autodl 数据盘只有 50GB，本次需要为 `prepared_data_v2` 增加确定性的本地清理策略。

## 2. 目标

1. 为 `prepared_data_v2` 提供稳定的磁盘占用上限。
2. 清理长期未访问的冷缓存，避免旧目录无限累积。
3. 保持现有缓存目录结构与 fingerprint 兼容，不破坏命中逻辑。
4. 在异常中断、索引残留、临时目录残留时具备自愈能力。

## 3. 非目标

1. 不改动 `AssetCache` 的行为与阈值。
2. 不改变 `prepared_data_v2` 的 fingerprint 组成。
3. 不把 prepared data cache 升级为远端缓存或跨 executor 共享缓存。

## 4. 约束

默认阈值固定为：

- `PREPARED_DATA_CACHE_MAX_BYTES = 10 * 1024 * 1024 * 1024`
- `PREPARED_DATA_CACHE_MAX_AGE_HOURS = 24`
- `PREPARED_DATA_CACHE_STARTUP_PRUNE_ENABLED = true`

其中容量上限优先用于控盘，时间过期用于清理冷数据。

## 5. 方案选型

### 5.1 备选方案

1. 仅 TTL 清理
2. 仅容量上限 + LRU 淘汰
3. 容量上限优先 + TTL 兜底

### 5.2 选择

采用方案 3。

理由：

1. 仅 TTL 不能保证磁盘一定受控。
2. 仅容量上限会让长期冷缓存只在“磁盘爆满”时才被回收。
3. 两者结合可以同时满足控盘和清理冷数据两个目标，且与现有 `AssetCache` 的治理思路一致。

## 6. 设计

### 6.1 存储结构

保持目录结构不变：

- `cache/prepared_data_v2/<fingerprint>`

新增索引文件：

- `cache/prepared_data_v2/cache_index.json`

### 6.2 索引字段

每条记录包含：

- `path`
- `size_bytes`
- `created_at`
- `last_access_at`
- `source_task_id`

索引 key 使用 `fingerprint`。

### 6.3 生命周期

#### 恢复命中

`restore_prepared_data_cache(fingerprint)`：

1. 检查缓存目录是否存在且为目录。
2. 若命中，则把目录恢复到 `workspace.data_dir`。
3. 更新索引中的 `last_access_at` 与 `size_bytes`。
4. 不在命中路径中执行 prune，避免读取链路额外抖动。

#### 写入缓存

`store_prepared_data_cache(fingerprint, source_task_id)`：

1. 保持当前“先写临时目录，再 rename”为最终目录的原子写入方式。
2. 写入成功后统计目录大小并更新索引。
3. 立即执行一次 prune。
4. 当前刚写入的 fingerprint 作为 protected key，不参与本轮淘汰。

#### 启动清理

executor 启动后做一次 best-effort prune：

1. 删除 `.tmp-*` 遗留目录。
2. 清理索引脏项。
3. 执行 TTL 清理。
4. 如仍超限，再执行 LRU 容量淘汰。

### 6.4 淘汰顺序

固定顺序如下：

1. 清理脏项
2. 清理过期项
3. 清理超量项

其中超量项按 `last_access_at` 从旧到新淘汰。

### 6.5 竞态与安全性

1. 当前恢复命中的 fingerprint 不应被 startup prune 或写后 prune 误删。
2. 当前刚写入成功的 fingerprint 不参与本轮容量淘汰。
3. 索引损坏时允许回退为空索引，并通过目录重扫逐步自愈。
4. 目录缺失或删除失败不会中断主执行链路，只记录 best-effort 结果。

## 7. 代码边界

### 7.1 新增模块

新增 `saki_executor/cache/prepared_data_cache.py`，负责：

1. 读写索引
2. 统计目录大小
3. touch 命中项
4. prune 脏项、过期项、超量项

### 7.2 现有接线

1. `core/config.py` 增加配置项。
2. `steps/workspace.py` 的 prepared data cache 读写改为调用 helper。
3. `main.py` 在 executor 启动时触发一次 best-effort prune。

## 8. 测试策略

至少覆盖以下场景：

1. 命中恢复后更新时间戳。
2. 超过 24 小时的缓存会被清理。
3. 总大小超过 10GB 时按 LRU 淘汰。
4. 残留 `.tmp-*` 目录会被清理。
5. 索引中存在但磁盘目录已缺失的记录会被剔除。
6. 刚写入的 fingerprint 不会在同轮 prune 中被删。

## 9. 风险

1. 目录大小统计会带来少量 I/O 开销，但只发生在写入、命中和启动清理，不在主循环高频路径。
2. 多任务并发读写同一缓存根目录时仍需依赖 helper 的锁保护索引更新。
3. 现阶段不做跨进程锁，默认同一 executor 进程内协调即可；若后续引入多进程共享同一 cache root，再补文件锁。
