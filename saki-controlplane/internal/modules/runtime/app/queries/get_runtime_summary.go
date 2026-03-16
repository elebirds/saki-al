package queries

import (
	"context"
	"sync"
	"time"
)

type RuntimeSummary struct {
	PendingTasks int32
	RunningTasks int32
	LeaderEpoch  int64
}

type RuntimeExecutor struct {
	ID         string
	Version    string
	LastSeenAt time.Time
}

type AdminStore interface {
	GetRuntimeSummary(ctx context.Context) (RuntimeSummary, error)
	ListRuntimeExecutors(ctx context.Context) ([]RuntimeExecutor, error)
	CancelRuntimeTask(ctx context.Context, taskID string) error
}

type MemoryAdminStore struct {
	mu        sync.RWMutex
	summary   RuntimeSummary
	executors []RuntimeExecutor
}

func NewMemoryAdminStore() *MemoryAdminStore {
	return &MemoryAdminStore{
		summary: RuntimeSummary{},
	}
}

func (s *MemoryAdminStore) GetRuntimeSummary(context.Context) (RuntimeSummary, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.summary, nil
}

func (s *MemoryAdminStore) ListRuntimeExecutors(context.Context) ([]RuntimeExecutor, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	executors := make([]RuntimeExecutor, len(s.executors))
	copy(executors, s.executors)
	return executors, nil
}

func (s *MemoryAdminStore) CancelRuntimeTask(context.Context, string) error {
	return nil
}

type GetRuntimeSummaryQuery struct {
	store AdminStore
}

func NewGetRuntimeSummaryQuery(store AdminStore) *GetRuntimeSummaryQuery {
	return &GetRuntimeSummaryQuery{store: store}
}

func (q *GetRuntimeSummaryQuery) Execute(ctx context.Context) (RuntimeSummary, error) {
	return q.store.GetRuntimeSummary(ctx)
}
