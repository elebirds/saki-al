package commands

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

type TaskLoader interface {
	GetTask(ctx context.Context, taskID uuid.UUID) (*TaskRecord, error)
}

type CompleteTaskCommand struct {
	TaskID uuid.UUID
}

type CompleteTaskHandler struct {
	tasks interface {
		TaskLoader
		UpdateTask(ctx context.Context, update TaskUpdate) error
	}
	outbox OutboxWriter
}

func NewCompleteTaskHandler(tasks interface {
	TaskLoader
	UpdateTask(ctx context.Context, update TaskUpdate) error
}, outbox OutboxWriter) *CompleteTaskHandler {
	return &CompleteTaskHandler{
		tasks:  tasks,
		outbox: outbox,
	}
}

func (h *CompleteTaskHandler) Handle(ctx context.Context, cmd CompleteTaskCommand) (*TaskRecord, error) {
	task, err := h.tasks.GetTask(ctx, cmd.TaskID)
	if err != nil || task == nil {
		return task, err
	}

	snapshot := state.TaskSnapshot{Status: state.TaskStatus(task.Status)}
	if snapshot.Status != state.TaskStatusRunning {
		return nil, state.ErrInvalidTransition
	}

	events, err := state.DecideTask(snapshot, state.FinishTask{})
	if err != nil {
		return nil, err
	}

	for _, event := range events {
		snapshot = state.EvolveTask(snapshot, event)
	}

	update := TaskUpdate{
		ID:              task.ID,
		Status:          string(snapshot.Status),
		AssignedAgentID: task.AssignedAgentID,
		LeaderEpoch:     task.LeaderEpoch,
	}
	if err := h.tasks.UpdateTask(ctx, update); err != nil {
		return nil, err
	}

	payload, err := json.Marshal(struct {
		TaskID uuid.UUID `json:"task_id"`
		Status string    `json:"status"`
	}{
		TaskID: task.ID,
		Status: update.Status,
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

	completed := *task
	completed.Status = update.Status
	return &completed, nil
}
