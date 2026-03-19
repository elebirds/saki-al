package recovery

import (
	"context"
	"time"
)

type Store interface {
	MarkOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error)
	RequeueAssignedTasksWithoutAck(ctx context.Context, ackBefore time.Time) (int64, error)
	FailRunningTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error)
	CancelRequestedTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error)
}

// Worker 只做恢复判定与顺序编排，具体状态推进必须落在 repo 的原子 SQL 内完成。
// 这样 recovery 不会出现“task 已回滚，但旧 command 仍可投递”的撕裂状态。
type Worker struct {
	store  Store
	policy Policy
	now    func() time.Time
}

func NewWorker(store Store, policy Policy) *Worker {
	return &Worker{
		store:  store,
		policy: policy.withDefaults(),
		now:    time.Now,
	}
}

func (w *Worker) SetNow(now func() time.Time) {
	if now == nil {
		return
	}
	w.now = now
}

func (w *Worker) RunOnce(ctx context.Context) error {
	now := w.now()
	offlineBefore := now.Add(-w.policy.AgentHeartbeatTimeout)
	ackBefore := now.Add(-w.policy.AssignAckTimeout)

	// 顺序不能改：
	// 1. 先把 stale agent 标记为 offline，统一“失联”事实；
	// 2. 再回收未 ack 的 assign，避免旧命令继续占着 assignment；
	// 3. 最后处理 running/cancel_requested，基于离线 agent 推进终态。
	if _, err := w.store.MarkOfflineAgents(ctx, offlineBefore); err != nil {
		return err
	}
	if _, err := w.store.RequeueAssignedTasksWithoutAck(ctx, ackBefore); err != nil {
		return err
	}
	if _, err := w.store.FailRunningTasksForOfflineAgents(ctx, offlineBefore); err != nil {
		return err
	}
	if _, err := w.store.CancelRequestedTasksForOfflineAgents(ctx, offlineBefore); err != nil {
		return err
	}
	return nil
}
