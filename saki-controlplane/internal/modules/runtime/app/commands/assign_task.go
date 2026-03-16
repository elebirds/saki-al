package commands

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

type TaskRecord struct {
	ID          uuid.UUID
	TaskType    string
	Status      string
	ClaimedBy   string
	LeaderEpoch int64
}

type TaskUpdate struct {
	ID          uuid.UUID
	Status      string
	ClaimedBy   string
	LeaderEpoch int64
}

type OutboxEvent struct {
	Topic       string
	AggregateID string
	Payload     []byte
}

type TaskStore interface {
	NextPendingTask(ctx context.Context) (*TaskRecord, error)
	UpdateTask(ctx context.Context, update TaskUpdate) error
}

type OutboxWriter interface {
	Append(ctx context.Context, event OutboxEvent) error
}

type AssignTaskCommand struct {
	ClaimedBy   string
	LeaderEpoch int64
}

type AssignTaskHandler struct {
	tasks  TaskStore
	outbox OutboxWriter
}

func NewAssignTaskHandler(tasks TaskStore, outbox OutboxWriter) *AssignTaskHandler {
	return &AssignTaskHandler{
		tasks:  tasks,
		outbox: outbox,
	}
}

func (h *AssignTaskHandler) Handle(ctx context.Context, cmd AssignTaskCommand) (*TaskRecord, error) {
	task, err := h.tasks.NextPendingTask(ctx)
	if err != nil || task == nil {
		return task, err
	}

	snapshot := state.TaskSnapshot{Status: state.TaskStatus(task.Status)}
	events, err := state.DecideTask(snapshot, state.StartTask{})
	if err != nil {
		return nil, err
	}

	for _, event := range events {
		snapshot = state.EvolveTask(snapshot, event)
	}

	update := TaskUpdate{
		ID:          task.ID,
		Status:      string(snapshot.Status),
		ClaimedBy:   cmd.ClaimedBy,
		LeaderEpoch: cmd.LeaderEpoch,
	}
	if err := h.tasks.UpdateTask(ctx, update); err != nil {
		return nil, err
	}

	payload, err := json.Marshal(struct {
		TaskID      uuid.UUID `json:"task_id"`
		ClaimedBy   string    `json:"claimed_by"`
		LeaderEpoch int64     `json:"leader_epoch"`
	}{
		TaskID:      task.ID,
		ClaimedBy:   cmd.ClaimedBy,
		LeaderEpoch: cmd.LeaderEpoch,
	})
	if err != nil {
		return nil, err
	}

	if err := h.outbox.Append(ctx, OutboxEvent{
		Topic:       "runtime.task.assigned",
		AggregateID: task.ID.String(),
		Payload:     payload,
	}); err != nil {
		return nil, err
	}

	assigned := *task
	assigned.Status = update.Status
	assigned.ClaimedBy = update.ClaimedBy
	assigned.LeaderEpoch = update.LeaderEpoch

	return &assigned, nil
}
