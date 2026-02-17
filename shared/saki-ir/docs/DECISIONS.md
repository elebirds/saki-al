# Saki IR v1 决策记录（DECISIONS）

本文档记录 v1 冻结期的关键工程决策。格式：`Decision / Rationale / Consequences`。

| Decision | Rationale | Consequences |
|---|---|---|
| Rect 使用 top-left + size（`x,y,width,height`） | 与大多数检测标注工具和数据集格式一致，互操作成本低 | 调用方必须明确 Rect 不是 center 语义；转换到 center 需显式公式 |
| OBB 使用 center + size + `angle_deg_cw` | OBB 旋转表达更稳定，便于几何推导和顶点计算 | 必须遵守角度方向定义；实现和测试需锁定 `angle_deg_cw` 语义 |
| 角度单位使用 degree（非 radian） | 人类可读、便于标注工具配置与调试 | 几何实现内部可转弧度，但 API/存储层统一为 degree |
| 几何字段使用 float32（proto `float`） | 压缩体积更小，跨语言 protobuf 一致 | 计算时可用 float64 中间值，但写回时按 float32 语义比较 |
| 业务 ID 使用 string（通常承载 UUID） | 跨系统迁移简单，不绑定某一语言整数类型 | 不在 IR 层强制 UUID 校验，约束由上层业务决定 |
| payload codec 默认 PROTOBUF | protobuf 在跨语言、性能、工具链上最稳定 | MSGPACK 仅保留枚举位；v1 未实现必须返回明确错误 |
| 压缩策略：阈值 32768，ZSTD level=3，无 dictionary | 在压缩率和 CPU 成本间取得稳健折中 | SDK 默认值需一致；小 payload 走 NONE，避免无效压缩开销 |
| checksum 使用 CRC32C(Castagnoli) 且覆盖未压缩 payload_raw | 与存储/网络领域常用校验兼容，且避免“压缩实现差异”影响一致性 | 校验必须在解压后执行；压缩前后 payload bytes 不可混淆 |
| Dispatcher 采用 header-only 读取 stats | 调度阶段只需统计信息，不应为此解压/解码 | `ReadHeader` 必须可独立工作；verify checksum 可解压但无需 decode |
