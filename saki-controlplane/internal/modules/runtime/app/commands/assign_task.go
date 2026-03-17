package commands

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
)

const AssignTaskOutboxTopic = "runtime.task.assign.v1"

type TaskRecord struct {
	ID                 uuid.UUID
	TaskKind           string
	TaskType           string
	Status             string
	CurrentExecutionID string
	AssignedAgentID    string
	Attempt            int32
	MaxAttempts        int32
	ResolvedParams     []byte
	DependsOnTaskIDs   []uuid.UUID
	LeaderEpoch        int64
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

type AssignClaimParams struct {
	AssignedAgentID string
	LeaderEpoch     int64
}

type ClaimedTask struct {
	ID                 uuid.UUID
	TaskKind           string
	TaskType           string
	Status             string
	CurrentExecutionID string
	AssignedAgentID    string
	Attempt            int32
	MaxAttempts        int32
	ResolvedParams     []byte
	DependsOnTaskIDs   []uuid.UUID
	LeaderEpoch        int64
}

type AssignTaskOutboxPayload struct {
	TaskID           uuid.UUID       `json:"task_id"`
	ExecutionID      string          `json:"execution_id"`
	AgentID          string          `json:"agent_id"`
	TaskKind         string          `json:"task_kind"`
	TaskType         string          `json:"task_type"`
	Attempt          int32           `json:"attempt"`
	MaxAttempts      int32           `json:"max_attempts"`
	ResolvedParams   json.RawMessage `json:"resolved_params"`
	DependsOnTaskIDs []uuid.UUID     `json:"depends_on_task_ids"`
	LeaderEpoch      int64           `json:"leader_epoch"`
}

type TaskClaimer interface {
	AssignPendingTask(ctx context.Context, params AssignClaimParams) (*ClaimedTask, error)
}

type OutboxWriter interface {
	Append(ctx context.Context, event OutboxEvent) error
}

type AssignTaskCommand struct {
	AssignedAgentID string
	LeaderEpoch     int64
}

type AssignTaskHandler struct {
	tasks  TaskClaimer
	outbox OutboxWriter
}

func NewAssignTaskHandler(tasks TaskClaimer, outbox OutboxWriter) *AssignTaskHandler {
	return &AssignTaskHandler{
		tasks:  tasks,
		outbox: outbox,
	}
}

func (h *AssignTaskHandler) Handle(ctx context.Context, cmd AssignTaskCommand) (*TaskRecord, error) {
	task, err := h.tasks.AssignPendingTask(ctx, AssignClaimParams{
		AssignedAgentID: cmd.AssignedAgentID,
		LeaderEpoch:     cmd.LeaderEpoch,
	})
	if err != nil || task == nil {
		return nil, err
	}

	payload, err := json.Marshal(assignTaskOutboxPayloadFromClaim(task))
	if err != nil {
		return nil, err
	}

	if err := h.outbox.Append(ctx, OutboxEvent{
		Topic:          AssignTaskOutboxTopic,
		AggregateID:    task.ID.String(),
		IdempotencyKey: assignTaskOutboxIdempotencyKey(task.CurrentExecutionID),
		Payload:        payload,
	}); err != nil {
		return nil, err
	}

	return taskRecordFromClaimedTask(task), nil
}

func assignTaskOutboxPayloadFromClaim(task *ClaimedTask) AssignTaskOutboxPayload {
	return AssignTaskOutboxPayload{
		TaskID:           task.ID,
		ExecutionID:      task.CurrentExecutionID,
		AgentID:          task.AssignedAgentID,
		TaskKind:         task.TaskKind,
		TaskType:         task.TaskType,
		Attempt:          task.Attempt,
		MaxAttempts:      task.MaxAttempts,
		ResolvedParams:   normalizedResolvedParams(task.ResolvedParams),
		DependsOnTaskIDs: append([]uuid.UUID(nil), task.DependsOnTaskIDs...),
		LeaderEpoch:      task.LeaderEpoch,
	}
}

func taskRecordFromClaimedTask(task *ClaimedTask) *TaskRecord {
	return &TaskRecord{
		ID:                 task.ID,
		TaskKind:           task.TaskKind,
		TaskType:           task.TaskType,
		Status:             task.Status,
		CurrentExecutionID: task.CurrentExecutionID,
		AssignedAgentID:    task.AssignedAgentID,
		Attempt:            task.Attempt,
		MaxAttempts:        task.MaxAttempts,
		ResolvedParams:     append([]byte(nil), task.ResolvedParams...),
		DependsOnTaskIDs:   append([]uuid.UUID(nil), task.DependsOnTaskIDs...),
		LeaderEpoch:        task.LeaderEpoch,
	}
}

func normalizedResolvedParams(raw []byte) json.RawMessage {
	if len(raw) == 0 {
		return json.RawMessage(`{}`)
	}
	return json.RawMessage(append([]byte(nil), raw...))
}

func assignTaskOutboxIdempotencyKey(executionID string) string {
	return fmt.Sprintf("%s:%s", AssignTaskOutboxTopic, executionID)
}
