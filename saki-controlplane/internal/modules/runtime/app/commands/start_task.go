package commands

import (
	"context"
	"errors"

	"github.com/google/uuid"
)

var ErrExecutionIDRequired = errors.New("execution id is required")

type StartTaskCommand struct {
	TaskID      uuid.UUID
	ExecutionID string
}

type StartTaskHandler struct {
	tasks ExecutionScopedTaskStore
}

func NewStartTaskHandler(tasks ExecutionScopedTaskStore) *StartTaskHandler {
	return &StartTaskHandler{tasks: tasks}
}

func (h *StartTaskHandler) Handle(ctx context.Context, cmd StartTaskCommand) (*TaskRecord, error) {
	task, _, err := advanceTaskByExecution(ctx, h.tasks, AdvanceTaskByExecutionParams{
		ID:           cmd.TaskID,
		ExecutionID:  cmd.ExecutionID,
		FromStatuses: []string{"assigned"},
		NoopStatuses: []string{"running", "cancel_requested", "succeeded", "failed", "canceled"},
		ToStatus:     "running",
	})
	return task, err
}
