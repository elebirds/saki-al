package commands

import (
	"context"
	"encoding/json"

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
	tasks  ExecutionScopedTaskStore
	outbox OutboxWriter
}

func NewCompleteTaskHandler(tasks ExecutionScopedTaskStore, outbox OutboxWriter) *CompleteTaskHandler {
	return &CompleteTaskHandler{
		tasks:  tasks,
		outbox: outbox,
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

	payload, err := json.Marshal(struct {
		TaskID      uuid.UUID `json:"task_id"`
		ExecutionID string    `json:"execution_id"`
		Status      string    `json:"status"`
	}{
		TaskID:      task.ID,
		ExecutionID: task.CurrentExecutionID,
		Status:      task.Status,
	})
	if err != nil {
		return nil, err
	}

	if err := h.outbox.Append(ctx, OutboxEvent{
		Topic:       "runtime.task.completed",
		AggregateID: task.ID.String(),
		Payload:     payload,
	}); err != nil {
		return nil, err
	}

	return task, nil
}
