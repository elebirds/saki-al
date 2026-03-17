package commands

import (
	"context"

	"github.com/google/uuid"
)

type FailTaskCommand struct {
	TaskID      uuid.UUID
	ExecutionID string
}

type FailTaskHandler struct {
	tasks ExecutionScopedTaskStore
}

func NewFailTaskHandler(tasks ExecutionScopedTaskStore) *FailTaskHandler {
	return &FailTaskHandler{tasks: tasks}
}

func (h *FailTaskHandler) Handle(ctx context.Context, cmd FailTaskCommand) (*TaskRecord, error) {
	task, _, err := advanceTaskByExecution(ctx, h.tasks, AdvanceTaskByExecutionParams{
		ID:           cmd.TaskID,
		ExecutionID:  cmd.ExecutionID,
		FromStatuses: []string{"running", "cancel_requested"},
		ToStatus:     "failed",
	})
	return task, err
}
