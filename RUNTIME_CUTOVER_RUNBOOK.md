# Runtime 协议一次性切换 Runbook

## 1. 目标

将 Runtime 通信从旧实现切换到 protobuf 强类型 `RuntimeMessage`，并保持 API 与 Executor 一致发布，禁止混跑。

## 2. 发布前检查

1. 两端代码均已基于同一版 `proto/runtime_control.proto` 重新生成 `pb2/pb2_grpc`。
2. `saki-api` 与 `saki-executor` 依赖满足：
   - `grpcio>=1.78.0`
   - `protobuf>=6.31.1,<7`
3. 回归测试通过：
   - `cd saki-api && uv run --with pytest pytest tests/runtime -q`
   - `cd saki-executor && uv run --with pytest pytest tests -q`
4. 生产环境参数已确认：
   - `INTERNAL_TOKEN`
   - `RUNTIME_EXECUTOR_ALLOWLIST`
   - `RUNTIME_ASSIGN_ACK_TIMEOUT_SEC`
   - `RUNTIME_STREAM_REJECT_CLOSE`
   - `RUNTIME_REQUEST_IDEMPOTENCY_TTL_SEC`
   - `RUNTIME_REQUEST_IDEMPOTENCY_MAX_ENTRIES`

## 3. 发布窗口操作

1. 进入维护窗口，暂停新任务创建或将任务调度入口置为只读。
2. 先发布 `saki-api`（包含新 gRPC 服务端与调度/幂等逻辑）。
3. 再发布 `saki-executor`（所有实例一并升级）。
4. 确认所有 executor 重新注册在线，且无旧版本实例残留。
5. 确认 API 启动日志中出现“runtime restart recovery completed”，并检查恢复摘要。

## 4. 验证清单

1. Executor 启动日志包含注册成功与心跳日志。
2. API 侧可观察到 executor 在线、任务可派发。
3. 端到端演练一条任务链路：
   - `assign_job -> ack -> job_event -> job_result -> mark_idle`
4. 重复 `request_id` 验证：
   - `data_request/upload_ticket_request` 返回缓存响应，不重复执行业务。
   - `job_event/job_result/ack` 重放不重复写入与状态推进。

## 5. 回滚策略

1. 若切换失败，API 与 Executor 必须同时回滚到上一个稳定 tag。
2. 由于不保留双栈兼容，禁止只回滚单边服务。
3. 回滚后重新验证：
   - executor 可注册
   - 任务可派发并结束
   - 前端查询任务详情与日志正常

## 6. 常见故障与处理

1. `UNAUTHENTICATED`：检查 `INTERNAL_TOKEN` 是否一致。
2. `FORBIDDEN`：检查 `RUNTIME_EXECUTOR_ALLOWLIST` 是否包含该 `executor_id`。
3. `UNAVAILABLE`：检查 API gRPC 监听地址、防火墙/NAT 出站策略。
4. 重复副作用：检查 API 幂等参数与日志，确认去重缓存未被误设为过小。

## 7. 回滚演练记录模板

> 建议每次发布窗口前至少完成一次演练，并将记录归档到变更单。

### 7.1 基本信息

1. 演练日期：
2. 演练负责人：
3. 参与人员：
4. 演练环境（staging/prod-shadow）：

### 7.2 演练步骤与结果

1. 发布前状态确认（executor 在线数、pending 任务数）：
2. 执行切换动作（API tag / Executor tag）：
3. 触发回滚动作（API tag / Executor tag）：
4. 回滚后验证（注册、派发、事件、结果、前端查询）：

### 7.3 观测与结论

1. 关键耗时（分钟）：
2. 发现问题：
3. 临时缓解措施：
4. 后续修复项（owner + 截止日期）：
