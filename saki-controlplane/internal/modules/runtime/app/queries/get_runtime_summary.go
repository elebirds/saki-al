package queries

import (
	"context"
	"sync"
	"time"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
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

type GetRuntimeSummaryQuery struct {
	store AdminStore
}

func NewGetRuntimeSummaryQuery(store AdminStore) *GetRuntimeSummaryQuery {
	return &GetRuntimeSummaryQuery{store: store}
}

func (q *GetRuntimeSummaryQuery) Execute(ctx context.Context) (RuntimeSummary, error) {
	return q.store.GetRuntimeSummary(ctx)
}

type RepoAdminStore struct {
	tasks     *runtimerepo.TaskRepo
	executors *runtimerepo.ExecutorRepo
}

func NewRepoAdminStore(tasks *runtimerepo.TaskRepo, executors *runtimerepo.ExecutorRepo) *RepoAdminStore {
	return &RepoAdminStore{
		tasks:     tasks,
		executors: executors,
	}
}

func (s *RepoAdminStore) GetRuntimeSummary(ctx context.Context) (RuntimeSummary, error) {
	summary, err := s.tasks.GetSummary(ctx)
	if err != nil {
		return RuntimeSummary{}, err
	}

	return RuntimeSummary{
		PendingTasks: summary.PendingTasks,
		RunningTasks: summary.RunningTasks,
		LeaderEpoch:  summary.LeaderEpoch,
	}, nil
}

func (s *RepoAdminStore) ListRuntimeExecutors(ctx context.Context) ([]RuntimeExecutor, error) {
	executors, err := s.executors.List(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]RuntimeExecutor, 0, len(executors))
	for _, executor := range executors {
		result = append(result, RuntimeExecutor{
			ID:         executor.ID,
			Version:    executor.Version,
			LastSeenAt: executor.LastSeenAt,
		})
	}

	return result, nil
}
