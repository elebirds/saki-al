# Runtime Round 聚合事件流实时化设计 v1

## 1. 目标
- Round/Loop 页面统一使用 `round events` 作为实时主通道。
- 退出页面内 `step events` 周期轮询与训练指标轮询。
- 正常态仅 WS 驱动；异常态仅断线补偿（低频）。

## 2. 接口
- 新增 HTTP: `GET /rounds/{round_id}/events`
- 新增 WS: `WS /rounds/{round_id}/events/ws`
- Cursor: `base64url(json)`，内容为 `{"v":1,"step_seq":{"<step_id>":<max_seq>}}`

## 3. 服务端实现
- `RuntimeQueryMixin.query_round_events` 聚合 round 下多 step 事件。
- `StepEventRepository.list_by_round_after_cursor` 支持按 `step_id + seq` 增量查询。
- HTTP 返回 `items/next_after_cursor/has_more`。
- WS 使用相同查询函数周期拉增量并逐条推送。
- 保留 `/steps/{step_id}/events` 与 step ws，仅兼容，不再作为 Loop/Round 页面主通道。

## 4. 前端行为
### 4.1 Round 详情页
- 首次加载：`getRound + getRoundSteps + getRoundEvents(history)`。
- 建立 `round ws` 后实时 append 控制台。
- `metric(train)` 事件直接增量更新训练曲线。
- `status/artifact` 事件触发节流 `refreshRoundMeta`。
- 删除 step 级事件轮询与训练曲线轮询。

### 4.2 Loop 详情页
- 订阅最新 round 的 `round ws`。
- 事件到达后节流刷新 `refreshLoopData`。
- 最新 round 变化时自动切换订阅。
- 无 round 或 ws 不可用时启用 30s 补偿轮询。

## 5. 断线策略
- 指数退避重连：1s / 2s / 5s / 10s。
- 连续失败阈值后，先 `getRoundEvents(after_cursor)` 对齐，再继续重连。

## 6. 验收口径
- Round 页不再出现 `GET /steps/{id}/events` 周期请求。
- Round 页训练曲线可随 metric 事件增长。
- Loop 页进入后自动建立 round ws，状态可见。
- WS 断开时进入补偿，恢复后退出补偿。
