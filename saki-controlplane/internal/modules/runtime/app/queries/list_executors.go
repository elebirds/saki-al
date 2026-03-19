package queries

import "context"

type ListExecutorsQuery struct {
	store AdminStore
}

type ListAgentsQuery struct {
	store AdminStore
}

func NewListAgentsQuery(store AdminStore) *ListAgentsQuery {
	return &ListAgentsQuery{store: store}
}

func NewListExecutorsQuery(store AdminStore) *ListExecutorsQuery {
	return &ListExecutorsQuery{store: store}
}

func (q *ListAgentsQuery) Execute(ctx context.Context) ([]RuntimeAgent, error) {
	return q.store.ListRuntimeAgents(ctx)
}

func (q *ListExecutorsQuery) Execute(ctx context.Context) ([]RuntimeExecutor, error) {
	agents, err := q.store.ListRuntimeAgents(ctx)
	if err != nil {
		return nil, err
	}
	return agents, nil
}
