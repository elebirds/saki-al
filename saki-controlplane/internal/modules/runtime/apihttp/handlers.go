package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
)

type Handlers struct {
	summary   *runtimequeries.GetRuntimeSummaryQuery
	executors *runtimequeries.ListExecutorsQuery
	commands  *runtimequeries.IssueRuntimeCommandUseCase
}

type Dependencies struct {
	Store    runtimequeries.AdminStore
	Commands *runtimequeries.IssueRuntimeCommandUseCase
}

func NewHandlers(deps Dependencies) *Handlers {
	return &Handlers{
		summary:   runtimequeries.NewGetRuntimeSummaryQuery(deps.Store),
		executors: runtimequeries.NewListExecutorsQuery(deps.Store),
		commands:  deps.Commands,
	}
}

func (h *Handlers) GetRuntimeSummary(ctx context.Context) (*openapi.RuntimeSummaryResponse, error) {
	summary, err := h.summary.Execute(ctx)
	if err != nil {
		return nil, err
	}

	return &openapi.RuntimeSummaryResponse{
		PendingTasks: summary.PendingTasks,
		RunningTasks: summary.RunningTasks,
		LeaderEpoch:  summary.LeaderEpoch,
	}, nil
}

func (h *Handlers) ListRuntimeExecutors(ctx context.Context) ([]openapi.RuntimeExecutor, error) {
	executors, err := h.executors.Execute(ctx)
	if err != nil {
		return nil, err
	}

	result := make([]openapi.RuntimeExecutor, 0, len(executors))
	for _, executor := range executors {
		result = append(result, openapi.RuntimeExecutor{
			ID:         executor.ID,
			Version:    executor.Version,
			LastSeenAt: executor.LastSeenAt,
		})
	}

	return result, nil
}

func (h *Handlers) CancelRuntimeTask(ctx context.Context, params openapi.CancelRuntimeTaskParams) (*openapi.RuntimeCommandResponse, error) {
	if err := h.commands.CancelTask(ctx, params.TaskID); err != nil {
		return nil, err
	}

	return &openapi.RuntimeCommandResponse{
		Accepted: true,
	}, nil
}
