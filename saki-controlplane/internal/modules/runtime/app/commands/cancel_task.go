package commands

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

type CancelTaskCommand struct {
	TaskID uuid.UUID
}

type CancelTaskHandler struct {
	tasks interface {
		TaskLoader
		UpdateTask(ctx context.Context, update TaskUpdate) error
	}
	outbox OutboxWriter
}

func NewCancelTaskHandler(tasks interface {
	TaskLoader
	UpdateTask(ctx context.Context, update TaskUpdate) error
}, outbox OutboxWriter) *CancelTaskHandler {
	return &CancelTaskHandler{
		tasks:  tasks,
		outbox: outbox,
	}
}

func (h *CancelTaskHandler) Handle(ctx context.Context, cmd CancelTaskCommand) (*TaskRecord, error) {
	task, err := h.tasks.GetTask(ctx, cmd.TaskID)
	if err != nil || task == nil {
		return task, err
	}

	snapshot := state.TaskSnapshot{Status: state.TaskStatus(task.Status)}
	events, err := state.DecideTask(snapshot, state.RequestTaskCancel{})
	if err != nil {
		return nil, err
	}

	for _, event := range events {
		snapshot = state.EvolveTask(snapshot, event)
	}

	update := TaskUpdate{
		ID:          task.ID,
		Status:      string(snapshot.Status),
		ClaimedBy:   task.ClaimedBy,
		LeaderEpoch: task.LeaderEpoch,
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
		Topic:       "runtime.task.canceled",
		AggregateID: task.ID.String(),
		Payload:     payload,
	}); err != nil {
		return nil, err
	}

	canceled := *task
	canceled.Status = update.Status
	return &canceled, nil
}
