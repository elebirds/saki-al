# Saki Executor 具体实现全流程解析（任务如何真正跑起来）

> 版本基线：当前 `saki-executor` 实现（2026-02-12）
> 关注：任务启动、策略注册、插件执行、日志/指标/制品回传的完整链路。

---

## 0. 入口与装配

入口文件：`saki-executor/src/saki_executor/main.py`

启动流程：
1. 初始化日志系统。
2. `PluginRegistry.load_builtin()` 装载内置插件。
3. 创建 `AssetCache`、`JobManager`、`AgentClient`。
4. `manager.set_transport(client.send_message, client.request_message)` 打通上下行通道。
5. 启动两个并发任务：
   - gRPC 客户端 `client.run`
   - 本地命令服务 `CommandServer.run`

---

## 1. 执行器如何注册到 API

核心：`AgentClient.run`

步骤：
1. 连接 `settings.API_GRPC_TARGET`。
2. 建立 `RuntimeControl.Stream` 双向流。
3. 发送 `Register`：
   - executor_id/version
   - 插件能力列表
   - 机器资源（CPU/GPU/内存/accelerator）
4. 启动心跳协程 `_heartbeat_loop`。

注册成功判定：
- 收到 `ack(type=REGISTER, reason=REGISTERED, status=OK)`。
- `job_manager.executor_state` 切到 `IDLE`。

---

## 2. 任务是如何被接住的

入口：`AgentClient._handle_incoming` 收到 `assign_task`

处理逻辑：
1. 先查 `_handled_control_acks`（重复请求幂等回 ACK）。
2. `runtime_codec.parse_assign_task(assign)` 解析 payload。
3. 调 `job_manager.assign_task(request_id, task_payload)`。
4. 按结果回 `ACK`：
   - 接受：`accepted`
   - 拒绝（busy）：`executor_busy`

---

## 3. JobManager 如何启动任务协程

方法：`JobManager.assign_task`

行为：
1. `TaskExecutionRequest.from_payload` 做输入校验（task_id/mode/query_strategy/round_index）。
2. 锁保护下检查 `busy`。
3. 非 busy 时：
   - `current_task_id = task_id`
   - `executor_state = RESERVED`
   - 清理 stop 标志
   - 启动 `_run_task` 协程

---

## 4. _run_task 主流程

方法：`JobManager._run_task`

执行分支：
1. 正常：`JobPipelineRunner.run` 返回 `TaskFinalResult`
2. 取消：走 `_publish_cancelled_result`
3. 异常：走 `_publish_failed_result`
4. finally：统一 `_reset_after_task`

这保证任何异常都不会把 manager 卡在 running 状态。

---

## 5. JobPipelineRunner：任务内部执行顺序

方法：`jobs/orchestration/runner.py -> JobPipelineRunner.run`

顺序：
1. 校验 mode（active_learning/simulation/manual）
2. 解析并拿到插件实例（按 `plugin_id`）
3. 创建工作目录 `runs/{task_id}`，写 `config.json`
4. 发起状态事件：`PENDING -> DISPATCHING -> RUNNING`
5. 训练数据准备 + 插件训练
6. 候选样本采集
7. 制品上传
8. 结果终态回传（成功/失败）

---

## 6. 数据如何被拉下来

服务：`DataGateway`

协议动作：
1. 拉 labels：`DataRequest(query_type=labels)`
2. 拉 samples：`DataRequest(query_type=samples)`
3. 拉 annotations：`DataRequest(query_type=annotations)`
4. 采样阶段拉 unlabeled：`query_type=unlabeled_samples`

实现：
- `fetch_all` 按 cursor 翻页直到 next_cursor 为空。

---

## 7. 训练数据准备与缓存

模块：`TrainingDataService.prepare`

步骤：
1. 拉 labels/samples/annotations。
2. active_learning/simulation 下按 `annotations` 反推 labeled sample 集合。
3. 对训练样本逐个走 `AssetCache.ensure_cached`：
   - 下载到 `cache/assets/...`
   - SHA256 校验
   - 更新 LRU 索引

结果：
- 返回 `TrainingDataBundle(labels, train_samples, train_annotations, protected_hashes)`。

---

## 8. 插件如何执行训练与选样

接口：`ExecutorPlugin`

典型插件：`YoloDetectionPlugin`（实际委托 `YoloDetectionInternal`）

训练链：
1. `prepare_data` 生成训练格式（如 YOLO 数据集结构）
2. `train` 执行训练，产出 `TrainOutput(metrics, artifacts)`

选样链：
1. `SamplingService.collect_topk_candidates_streaming`
2. 分页拉未标注样本，调用 `plugin.predict_unlabeled_batch`
3. 用最小堆维护 topK

策略来源：
1. 插件原生策略（如 `plugin_native_strategy`）
2. 内置策略函数 `strategies/builtin.py`

---

## 9. 实时日志/进度/指标如何回传

本地事件生产：`JobReporter`（`events.jsonl`，带 seq）

发送器：`TaskEventEmitter`

消息化：`runtime_codec.build_task_event_message`

事件类型：
1. status
2. log
3. progress
4. metric
5. artifact（在 emitter 中以受控方式处理）

---

## 10. 制品回传如何完成

步骤：
1. `DataGateway.request_upload_ticket` 申请上传票据。
2. `ArtifactUploader.upload_with_retry` 用 HTTP PUT 上传。
3. 上传成功后把 `storage_uri` 写入 artifacts。
4. 同步发 artifact 事件。
5. 最终 `TaskResult` 带全量 artifacts 上报。

异常策略：
- required artifact 失败 -> 直接任务失败。
- optional artifact 失败 -> 汇总后按失败处理（当前实现是最终标 FAILED 并附错误）。

---

## 11. 任务终态如何发回 API

消息：`TaskResult`

字段：
1. status
2. metrics
3. artifacts
4. candidates
5. error_message

发送后 manager 做本地收尾：
- `executor_state -> IDLE`
- `current_task_id = None`
- 清理 active plugin 与 stop event

---

## 12. 停止任务路径（你排障常用）

入口：API 下发 `StopTask` -> client 收到 -> `JobManager.stop_task`

流程：
1. 检查当前任务是否匹配。
2. 设置 `_stop_event`。
3. 调 `plugin.stop(task_id)`（best effort）。
4. pipeline 检测 stop 后抛取消并走 `CANCELLED` 回传。

---

## 13. 配置项与行为关系

关键配置：`core/config.py`

1. `API_GRPC_TARGET`：控制面地址
2. `HEARTBEAT_INTERVAL_SEC`：心跳周期
3. `RUNS_DIR`：任务工作目录
4. `CACHE_DIR/CACHE_MAX_BYTES`：样本缓存
5. `INTERNAL_TOKEN`：gRPC metadata 鉴权
6. `DISCONNECT_FORCE_WAIT_SEC`：强制断开时等待停止时长

---

## 14. 插件与本体职责边界（实现规则）

推荐判定规则：

属于本体：
1. 连接、协议、重试、幂等
2. 任务生命周期和状态
3. 数据拉取、缓存、上传
4. 事件/结果规范

属于插件：
1. 数据格式转换细节
2. 训练与推理算法
3. 策略评分
4. 框架相关 stop 机制

边界打破会导致：
- 插件侵入控制链路，难维护；
- 本体耦合特定模型框架，难扩展。

---

## 15. 当前实现问题清单（给你评审时用）

P0：
1. 单任务串行模型吞吐受限；高并发必须横向扩实例。
2. 内部仍以 dict payload 为主，类型约束可继续提升。

P1：
1. `JobManager` 仍偏大，可继续拆分职责。
2. 本地 `events.jsonl` 与远端事件可能在极端网络故障下出现暂时偏差（最终以服务端落库为准）。

P2：
1. 命令系统基于 stdin，生产远程运维需另建控制接口。

---

## 16. 一句话总结

`saki-executor` 是“控制链路稳定 + 算法插件化”的执行代理：
- 任务启动靠 `assign_task -> manager -> runner`；
- 策略注册靠插件能力上报 + 内置策略函数；
- 插件和本体职责边界目前总体合理，后续重点在并发与类型收敛。
