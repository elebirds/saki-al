package queries

import "context"

type IssueRuntimeCommandUseCase struct {
	store AdminStore
}

func NewIssueRuntimeCommandUseCase(store AdminStore) *IssueRuntimeCommandUseCase {
	return &IssueRuntimeCommandUseCase{store: store}
}

func (u *IssueRuntimeCommandUseCase) CancelTask(ctx context.Context, taskID string) error {
	return u.store.CancelRuntimeTask(ctx, taskID)
}
