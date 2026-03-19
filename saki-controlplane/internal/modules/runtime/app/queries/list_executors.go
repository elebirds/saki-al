package queries

import "context"

type ListAgentsQuery struct {
	store AdminStore
}

func NewListAgentsQuery(store AdminStore) *ListAgentsQuery {
	return &ListAgentsQuery{store: store}
}

func (q *ListAgentsQuery) Execute(ctx context.Context) ([]RuntimeAgent, error) {
	return q.store.ListRuntimeAgents(ctx)
}
