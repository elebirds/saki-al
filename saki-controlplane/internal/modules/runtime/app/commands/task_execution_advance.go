package commands

import (
	"context"
	"errors"
	"slices"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

var ErrTaskTransitionConflict = errors.New("task transition compare-and-set failed")

type AdvanceTaskByExecutionParams struct {
	ID           uuid.UUID
	ExecutionID  string
	FromStatuses []string
	NoopStatuses []string
	ToStatus     string
}

type ExecutionScopedTaskStore interface {
	TaskLoader
	AdvanceTaskByExecution(ctx context.Context, params AdvanceTaskByExecutionParams) (*TaskRecord, error)
}

func advanceTaskByExecution(
	ctx context.Context,
	store ExecutionScopedTaskStore,
	params AdvanceTaskByExecutionParams,
) (*TaskRecord, bool, error) {
	if params.ExecutionID == "" {
		return nil, false, ErrExecutionIDRequired
	}

	updated, err := store.AdvanceTaskByExecution(ctx, params)
	if err != nil || updated != nil {
		return updated, updated != nil, err
	}

	task, err := store.GetTask(ctx, params.ID)
	if err != nil || task == nil {
		return task, false, err
	}
	if task.CurrentExecutionID != params.ExecutionID {
		return nil, false, nil
	}
	if task.Status == params.ToStatus || slices.Contains(params.NoopStatuses, task.Status) {
		return task, false, nil
	}
	if slices.Contains(params.FromStatuses, task.Status) {
		return nil, false, ErrTaskTransitionConflict
	}
	return nil, false, state.ErrInvalidTransition
}
