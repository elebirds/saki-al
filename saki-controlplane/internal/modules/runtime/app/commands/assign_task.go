package commands

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

type TaskRecord struct {
	ID              uuid.UUID
	TaskType        string
	Status          string
	AssignedAgentID string
	LeaderEpoch     int64
}

type TaskUpdate struct {
	ID              uuid.UUID
	Status          string
	AssignedAgentID string
	LeaderEpoch     int64
}

type OutboxEvent struct {
	Topic          string
	AggregateID    string
	IdempotencyKey string
	Payload        []byte
}

type TaskStore interface {
	NextPendingTask(ctx context.Context) (*TaskRecord, error)
	UpdateTask(ctx context.Context, update TaskUpdate) error
}

type OutboxWriter interface {
	Append(ctx context.Context, event OutboxEvent) error
}

type AssignTaskCommand struct {
	AssignedAgentID string
	LeaderEpoch     int64
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
	events, err := state.DecideTask(snapshot, state.AssignTask{})
	if err != nil {
		return nil, err
	}

	for _, event := range events {
		snapshot = state.EvolveTask(snapshot, event)
	}

	update := TaskUpdate{
		ID:              task.ID,
		Status:          string(snapshot.Status),
		AssignedAgentID: cmd.AssignedAgentID,
		LeaderEpoch:     cmd.LeaderEpoch,
	}
	if err := h.tasks.UpdateTask(ctx, update); err != nil {
		return nil, err
	}

	payload, err := json.Marshal(struct {
		TaskID          uuid.UUID `json:"task_id"`
		AssignedAgentID string    `json:"assigned_agent_id"`
		LeaderEpoch     int64     `json:"leader_epoch"`
	}{
		TaskID:          task.ID,
		AssignedAgentID: cmd.AssignedAgentID,
		LeaderEpoch:     cmd.LeaderEpoch,
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
	assigned.AssignedAgentID = update.AssignedAgentID
	assigned.LeaderEpoch = update.LeaderEpoch

	return &assigned, nil
}
