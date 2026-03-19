package runtime

import (
	"context"
	"log/slog"
	"time"
)

type recoveryWorker interface {
	RunOnce(context.Context) error
}

type recoveryTaskStore interface {
	RequeueAssignedTasksWithoutAck(ctx context.Context, ackBefore time.Time) (int64, error)
	FailRunningTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error)
	CancelRequestedTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error)
}

type recoveryAgentStore interface {
	MarkOfflineAgentsBefore(ctx context.Context, offlineBefore time.Time) (int64, error)
}

type noopRecoveryWorkerImpl struct{}

func (noopRecoveryWorkerImpl) RunOnce(context.Context) error {
	return nil
}

// runtimeRecoveryStore 把 recovery 需要的最小写集收敛到一个 store 上，
// 让 role 层只负责编排 loop，不把 repo 细节泄露到 recovery 策略里。
type runtimeRecoveryStore struct {
	tasks  recoveryTaskStore
	agents recoveryAgentStore
}

func newRuntimeRecoveryStore(tasks recoveryTaskStore, agents recoveryAgentStore) *runtimeRecoveryStore {
	return &runtimeRecoveryStore{
		tasks:  tasks,
		agents: agents,
	}
}

func (s *runtimeRecoveryStore) MarkOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	return s.agents.MarkOfflineAgentsBefore(ctx, offlineBefore)
}

func (s *runtimeRecoveryStore) RequeueAssignedTasksWithoutAck(ctx context.Context, ackBefore time.Time) (int64, error) {
	return s.tasks.RequeueAssignedTasksWithoutAck(ctx, ackBefore)
}

func (s *runtimeRecoveryStore) FailRunningTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	return s.tasks.FailRunningTasksForOfflineAgents(ctx, offlineBefore)
}

func (s *runtimeRecoveryStore) CancelRequestedTasksForOfflineAgents(ctx context.Context, offlineBefore time.Time) (int64, error) {
	return s.tasks.CancelRequestedTasksForOfflineAgents(ctx, offlineBefore)
}

func recoveryRunOnceFunc(worker recoveryWorker) func(context.Context) error {
	if worker == nil {
		worker = noopRecoveryWorkerImpl{}
	}
	return worker.RunOnce
}

func recoveryRoleLoop(parts assembly, logger *slog.Logger) loopRunner {
	if !parts.roles.Has(RuntimeRoleRecovery) {
		return nil
	}

	// recovery 是独立角色：scheduler 只产生新派发，recovery 只负责超时和失联后的状态收敛。
	return newPollingLoop(pollingLoopConfig{
		name:     "recovery",
		interval: durationOrDefault(0, defaultRecoveryInterval),
		runOnce:  recoveryRunOnceFunc(parts.recoveryWorker),
		logger:   logger,
	})
}
