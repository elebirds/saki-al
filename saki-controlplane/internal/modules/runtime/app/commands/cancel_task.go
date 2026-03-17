package commands

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

const StopTaskOutboxTopic = "runtime.task.stop.v1"

type StopTaskOutboxPayload struct {
	TaskID      uuid.UUID `json:"task_id"`
	ExecutionID string    `json:"execution_id"`
	AgentID     string    `json:"agent_id"`
	Reason      string    `json:"reason"`
	LeaderEpoch int64     `json:"leader_epoch"`
}

type CancelTaskCommand struct {
	TaskID uuid.UUID
}

type CancelTaskStore interface {
	TaskLoader
	UpdateTask(ctx context.Context, update TaskUpdate) error
	OutboxWriter
}

type CancelTaskTxRunner interface {
	InTx(ctx context.Context, fn func(store CancelTaskStore) error) error
}

type CancelTaskHandler struct {
	tx CancelTaskTxRunner
}

func NewCancelTaskHandler(store CancelTaskStore) *CancelTaskHandler {
	return &CancelTaskHandler{
		tx: inlineCancelTaskTxRunner{store: store},
	}
}

func NewCancelTaskHandlerWithTx(tx CancelTaskTxRunner) *CancelTaskHandler {
	return &CancelTaskHandler{
		tx: tx,
	}
}

func (h *CancelTaskHandler) Handle(ctx context.Context, cmd CancelTaskCommand) (*TaskRecord, error) {
	var canceled *TaskRecord
	if err := h.tx.InTx(ctx, func(store CancelTaskStore) error {
		task, err := store.GetTask(ctx, cmd.TaskID)
		if err != nil || task == nil {
			canceled = task
			return err
		}

		snapshot := state.TaskSnapshot{Status: state.TaskStatus(task.Status)}
		events, err := state.DecideTask(snapshot, state.RequestTaskCancel{})
		if err != nil {
			return err
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
		if err := store.UpdateTask(ctx, update); err != nil {
			return err
		}

		switch snapshot.Status {
		case state.TaskStatusCancelRequested:
			payload, err := json.Marshal(StopTaskOutboxPayload{
				TaskID:      task.ID,
				ExecutionID: task.CurrentExecutionID,
				AgentID:     task.AssignedAgentID,
				Reason:      string(state.TaskStatusCancelRequested),
				LeaderEpoch: task.LeaderEpoch,
			})
			if err != nil {
				return err
			}
			if err := store.Append(ctx, OutboxEvent{
				Topic:       StopTaskOutboxTopic,
				AggregateID: task.ID.String(),
				Payload:     payload,
			}); err != nil {
				return err
			}
		case state.TaskStatusCanceled:
		default:
			return state.ErrInvalidTransition
		}

		next := *task
		next.Status = update.Status
		canceled = &next
		return nil
	}); err != nil {
		return nil, err
	}

	return canceled, nil
}

type inlineCancelTaskTxRunner struct {
	store CancelTaskStore
}

func (r inlineCancelTaskTxRunner) InTx(_ context.Context, fn func(store CancelTaskStore) error) error {
	return fn(r.store)
}
