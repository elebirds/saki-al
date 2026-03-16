package queries

import "context"

type ListExecutorsQuery struct {
	store AdminStore
}

func NewListExecutorsQuery(store AdminStore) *ListExecutorsQuery {
	return &ListExecutorsQuery{store: store}
}

func (q *ListExecutorsQuery) Execute(ctx context.Context) ([]RuntimeExecutor, error) {
	return q.store.ListRuntimeExecutors(ctx)
}
