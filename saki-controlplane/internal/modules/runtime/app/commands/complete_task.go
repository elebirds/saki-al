package commands

import (
	"context"

	"github.com/google/uuid"
)

type TaskLoader interface {
	GetTask(ctx context.Context, taskID uuid.UUID) (*TaskRecord, error)
}

type CompleteTaskCommand struct {
	TaskID      uuid.UUID
	ExecutionID string
}

type CompleteTaskHandler struct {
	tasks ExecutionScopedTaskStore
}

func NewCompleteTaskHandler(tasks ExecutionScopedTaskStore) *CompleteTaskHandler {
	return &CompleteTaskHandler{
		tasks: tasks,
	}
}

func (h *CompleteTaskHandler) Handle(ctx context.Context, cmd CompleteTaskCommand) (*TaskRecord, error) {
	task, applied, err := advanceTaskByExecution(ctx, h.tasks, AdvanceTaskByExecutionParams{
		ID:           cmd.TaskID,
		ExecutionID:  cmd.ExecutionID,
		FromStatuses: []string{"running", "cancel_requested"},
		ToStatus:     "succeeded",
	})
	if err != nil || task == nil {
		return task, err
	}
	if !applied {
		return task, nil
	}
	return task, nil
}
