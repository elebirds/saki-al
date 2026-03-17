package commands

import (
	"context"

	"github.com/google/uuid"
)

type ConfirmTaskCanceledCommand struct {
	TaskID      uuid.UUID
	ExecutionID string
}

type ConfirmTaskCanceledHandler struct {
	tasks ExecutionScopedTaskStore
}

func NewConfirmTaskCanceledHandler(tasks ExecutionScopedTaskStore) *ConfirmTaskCanceledHandler {
	return &ConfirmTaskCanceledHandler{tasks: tasks}
}

func (h *ConfirmTaskCanceledHandler) Handle(ctx context.Context, cmd ConfirmTaskCanceledCommand) (*TaskRecord, error) {
	task, _, err := advanceTaskByExecution(ctx, h.tasks, AdvanceTaskByExecutionParams{
		ID:           cmd.TaskID,
		ExecutionID:  cmd.ExecutionID,
		FromStatuses: []string{"cancel_requested"},
		ToStatus:     "canceled",
	})
	return task, err
}
