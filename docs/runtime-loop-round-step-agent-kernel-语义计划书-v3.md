# Saki Runtime 语义计划书 v3（Agent / Kernel / Snapshot Manifest）

## 1. 定版目标
1. 本版替代 v2，作为 `saki-agent + saki-kernel-sdk + saki-kernels` 的唯一实现依据。
2. 协议版本维持 `v1`，允许破坏式重构与删库重建。
3. `saki-executor` 仅保留过渡代码路径，不再作为生产执行面。

## 2. 强制约束
1. `UUID v7 -> Ordinal(uint32)` 映射永久固定在 `dataset_snapshot_sample_ordinal`。
2. 删除样本仅允许 Tombstone，`ordinal` 不可更新、不可复用。
3. Kernel 严禁携带 MinIO 凭证；制品上传由 Agent 异步流式完成。
4. Agent 与 Kernel 通讯强制 `ZMQ over IPC(UDS)`，禁止 TCP。
5. M4/MPS 采用能力驱动降级，不做全局一刀切禁用。

## 3. 数据语义
1. 静态集合：`val`、`test` 在 Loop 创建后锁定，不参与后续采样。
2. 动态集合：`train`、`unlabeled` 通过 selector 边界移动。
3. Simulation 模式按轮次快照伪造可见集；Manual 模式使用固定 `train/val/test`。
4. 数据切分默认策略：`70/15/15` + 最小保底 `train_pool>=200,val>=50,test>=50`。
5. 微型数据集退化：`N<300` 时保证 `val>=1,test>=1`。

## 4. Manifest 与 Selector
1. Manifest 只传引用与选择器，不传海量文件名。
2. Selector 编码优先 `Roaring`，连续段回退 `Range`，并支持 `Bitset`。
3. 所有 selector 必须绑定 `snapshot_id`，校验不匹配立即拒绝执行。
4. `checksum + cardinality` 作为跨语言一致性契约，Go/Python 必须一致。

## 5. Agent / Kernel 边界
1. Agent 负责：
   - Kernel 生命周期（Start/Stop/Kill）
   - IPC socket 管理与权限控制
   - 输出日志流转发
   - 节点能力上报与健康检查
   - 本地输出制品上传 MinIO（异步）
2. Kernel 负责：
   - 纯 AI 训练/推理逻辑
   - 向 `workspace/output` 写本地产物
   - 发出 `artifact_local_ready` 事件
   - 通过 SDK 执行 `USE_CPU_FOR_LOSS` 降级逻辑

## 6. 运行时策略
1. 调度器在派发前执行 capability 匹配：
   - 插件能力
   - 节点能力
   - 内核能力声明（`kernel.yaml`）
2. 命中 MPS 风险时，注入：
   - `PYTORCH_ENABLE_MPS_FALLBACK=1`
   - `USE_CPU_FOR_LOSS=true`
3. 若节点不满足能力要求，自动 CPU 回退或拒绝派发并给出 reason。

## 7. Step 事件与制品归档
1. Kernel 发 `artifact_local_ready_event`（本地相对路径、hash、required）。
2. Agent 上传成功后发 `artifact_uploaded_event`（storage_uri、etag、checksum）。
3. 仅 `artifact_uploaded_event` 才允许进入 Step 最终 artifacts。
4. `required=true` 且上传失败：Step 失败；`required=false`：记 warning 并继续。

## 8. 恢复语义
1. `al_session_state` 固化 `snapshot_id + selector_bytes + cardinality + checksum`。
2. dispatcher/agent 重启后按 `al_session_state` 与 `round_dataset_view` 进行重放恢复。
3. `STOPPING` 继续收敛：重复发取消命令直到在途 Step 全部终态。

## 9. 阶段实施
1. A: 固化 proto/IR/schema 并统一代码生成。
2. B: 重建数据库与 sqlc。
3. C: 上线 `saki-agent`（IPC、生命周期、上传器）。
4. D: 上线 `saki-kernel-sdk`（manifest、symlink、事件、降级）。
5. E: 迁移首批 kernels（`kernel.yaml` 能力声明）。
6. F: 调度器能力匹配与 GPU 独占策略升级。
7. G: Web/API 视图与配置适配。
8. H: 下线 `saki-executor` 生产路径。

## 10. 验收基线
1. Ordinal 不复用与 tombstone 保留。
2. Kernel 无 MinIO 凭证，上传仅 Agent 完成。
3. 运行时仅 UDS，无 TCP 监听。
4. M4/MPS 策略按能力注入或回退。
5. selector bytes 的 cardinality/checksum Go/Python 一致。
