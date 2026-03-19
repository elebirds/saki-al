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

type RuntimeAgent struct {
	ID         string
	Version    string
	LastSeenAt time.Time
}

type RuntimeExecutor = RuntimeAgent

type AdminStore interface {
	GetRuntimeSummary(ctx context.Context) (RuntimeSummary, error)
	ListRuntimeAgents(ctx context.Context) ([]RuntimeAgent, error)
}

type MemoryAdminStore struct {
	mu        sync.RWMutex
	summary   RuntimeSummary
	executors []RuntimeAgent
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

func (s *MemoryAdminStore) ListRuntimeAgents(context.Context) ([]RuntimeAgent, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	agents := make([]RuntimeAgent, len(s.executors))
	copy(agents, s.executors)
	return agents, nil
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
	tasks  *runtimerepo.TaskRepo
	agents *runtimerepo.AgentRepo
}

func NewRepoAdminStore(tasks *runtimerepo.TaskRepo, agents *runtimerepo.AgentRepo) *RepoAdminStore {
	return &RepoAdminStore{
		tasks:  tasks,
		agents: agents,
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

func (s *RepoAdminStore) ListRuntimeAgents(ctx context.Context) ([]RuntimeAgent, error) {
	agents, err := s.agents.List(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]RuntimeAgent, 0, len(agents))
	for _, agent := range agents {
		result = append(result, RuntimeAgent{
			ID:         agent.ID,
			Version:    agent.Version,
			LastSeenAt: agent.LastSeenAt,
		})
	}

	return result, nil
}
