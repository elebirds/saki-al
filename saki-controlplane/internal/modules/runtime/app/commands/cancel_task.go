package commands

import (
	"context"
	"encoding/json"
	"time"

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
	GetTaskAssignmentByExecutionID(ctx context.Context, executionID string) (*TaskAssignmentRecord, error)
	GetAgentByID(ctx context.Context, agentID string) (*AgentRecord, error)
	AppendCancelCommand(ctx context.Context, params AppendCancelTaskCommandParams) error
	OutboxWriter
}

type CancelTaskTxRunner interface {
	InTx(ctx context.Context, fn func(store CancelTaskStore) error) error
}

type CancelTaskHandler struct {
	tx  CancelTaskTxRunner
	now func() time.Time
}

func NewCancelTaskHandler(store CancelTaskStore) *CancelTaskHandler {
	return &CancelTaskHandler{
		tx:  inlineCancelTaskTxRunner{store: store},
		now: time.Now,
	}
}

func NewCancelTaskHandlerWithTx(tx CancelTaskTxRunner) *CancelTaskHandler {
	return &CancelTaskHandler{
		tx:  tx,
		now: time.Now,
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
			// 迁移窗口里 cancel 也要双写到 agent_command；
			// 但老任务可能还没有 assignment 真相，因此查不到 assignment 时只保留旧 outbox 兼容路径。
			if task.CurrentExecutionID != "" && task.AssignedAgentID != "" {
				assignment, err := store.GetTaskAssignmentByExecutionID(ctx, task.CurrentExecutionID)
				if err != nil {
					return err
				}
				agent, err := store.GetAgentByID(ctx, task.AssignedAgentID)
				if err != nil {
					return err
				}
				if assignment != nil && agent != nil {
					now := h.now().UTC()
					if err := store.AppendCancelCommand(ctx, AppendCancelTaskCommandParams{
						CommandID:     uuid.New(),
						AgentID:       task.AssignedAgentID,
						TaskID:        task.ID,
						AssignmentID:  assignment.ID,
						TransportMode: agent.TransportMode,
						Payload:       payload,
						AvailableAt:   now,
						ExpireAt:      now.Add(defaultAssignCommandTTL),
					}); err != nil {
						return err
					}
				}
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
