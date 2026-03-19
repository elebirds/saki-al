package commands

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

const (
	AssignTaskOutboxTopic   = "runtime.task.assign.v1"
	defaultAssignCommandTTL = 5 * time.Minute
)

type PendingTask struct {
	ID               uuid.UUID
	TaskKind         string
	TaskType         string
	Attempt          int32
	MaxAttempts      int32
	ResolvedParams   []byte
	DependsOnTaskIDs []uuid.UUID
	// 迁移阶段 runtime_task 还没有单独落 required capabilities；
	// 空集合表示这是通用任务，任何满足在线与容量约束的 agent 都可以接。
	RequiredCapabilities []string
}

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

type CreateTaskAssignmentParams struct {
	TaskID      uuid.UUID
	Attempt     int32
	AgentID     string
	ExecutionID string
	Status      string
}

type TaskAssignmentRecord struct {
	ID          int64
	TaskID      uuid.UUID
	Attempt     int32
	AgentID     string
	ExecutionID string
	Status      string
}

type AssignClaimedTaskParams struct {
	TaskID          uuid.UUID
	AssignedAgentID string
	ExecutionID     string
	Attempt         int32
	LeaderEpoch     int64
}

type AppendAssignTaskCommandParams struct {
	CommandID     uuid.UUID
	AgentID       string
	TaskID        uuid.UUID
	AssignmentID  int64
	TransportMode string
	Payload       []byte
	AvailableAt   time.Time
	ExpireAt      time.Time
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

type AssignResult struct {
	TaskID       uuid.UUID
	AssignmentID int64
	ExecutionID  string
	AgentID      string
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

type PendingTaskClaimer interface {
	ClaimPendingTask(ctx context.Context) (*PendingTask, error)
}

type AssignableAgentLister interface {
	ListAssignableAgents(ctx context.Context) ([]AgentRecord, error)
}

type TaskAssignmentCreator interface {
	CreateTaskAssignment(ctx context.Context, params CreateTaskAssignmentParams) (*TaskAssignmentRecord, error)
}

type ClaimedTaskAssigner interface {
	AssignClaimedTask(ctx context.Context, params AssignClaimedTaskParams) (*ClaimedTask, error)
}

type AssignTaskCommandWriter interface {
	AppendAssignCommand(ctx context.Context, params AppendAssignTaskCommandParams) error
}

type AssignTaskAgentSelector interface {
	SelectAgent(task PendingTask, agents []AgentRecord) *AgentRecord
}

type TaskClaimer interface {
	AssignPendingTask(ctx context.Context, params AssignClaimParams) (*ClaimedTask, error)
}

type OutboxWriter interface {
	Append(ctx context.Context, event OutboxEvent) error
}

type AssignTaskTx interface {
	PendingTaskClaimer
	AssignableAgentLister
	TaskAssignmentCreator
	ClaimedTaskAssigner
	AssignTaskCommandWriter
	OutboxWriter
}

type AssignTaskTxRunner interface {
	InTx(ctx context.Context, fn func(store AssignTaskTx) error) error
}

type AssignTaskCommand struct {
	LeaderEpoch int64
}

type AssignTaskHandler struct {
	tx       AssignTaskTxRunner
	selector AssignTaskAgentSelector
	now      func() time.Time
}

func NewAssignTaskHandler(store AssignTaskTx, selector AssignTaskAgentSelector) *AssignTaskHandler {
	return &AssignTaskHandler{
		tx:       inlineAssignTaskTxRunner{store: store},
		selector: selector,
		now:      time.Now,
	}
}

func NewAssignTaskHandlerWithTx(tx AssignTaskTxRunner, selector AssignTaskAgentSelector) *AssignTaskHandler {
	return &AssignTaskHandler{
		tx:       tx,
		selector: selector,
		now:      time.Now,
	}
}

func (h *AssignTaskHandler) Handle(ctx context.Context, cmd AssignTaskCommand) (*AssignResult, error) {
	var assigned *AssignResult
	if err := h.tx.InTx(ctx, func(store AssignTaskTx) error {
		task, err := store.ClaimPendingTask(ctx)
		if err != nil || task == nil {
			return err
		}

		agents, err := store.ListAssignableAgents(ctx)
		if err != nil {
			return err
		}

		agent := h.selector.SelectAgent(*task, agents)
		if agent == nil {
			return nil
		}

		executionID := newAssignExecutionID()
		assignment, err := store.CreateTaskAssignment(ctx, CreateTaskAssignmentParams{
			TaskID:      task.ID,
			Attempt:     task.Attempt + 1,
			AgentID:     agent.ID,
			ExecutionID: executionID,
			Status:      "assigned",
		})
		if err != nil {
			return err
		}

		runtimeTask, err := store.AssignClaimedTask(ctx, AssignClaimedTaskParams{
			TaskID:          task.ID,
			AssignedAgentID: agent.ID,
			ExecutionID:     executionID,
			Attempt:         task.Attempt + 1,
			LeaderEpoch:     cmd.LeaderEpoch,
		})
		if err != nil {
			return err
		}

		payload, err := json.Marshal(assignTaskOutboxPayloadFromClaim(runtimeTask))
		if err != nil {
			return err
		}

		now := h.now().UTC()
		// 迁移窗口里同时写新 command 真相和旧 outbox。
		// 这里必须放在同一事务里，避免出现 task 已 assigned 但新旧两条投递主线只成功一边的撕裂状态。
		if err := store.AppendAssignCommand(ctx, AppendAssignTaskCommandParams{
			CommandID:     uuid.New(),
			AgentID:       agent.ID,
			TaskID:        runtimeTask.ID,
			AssignmentID:  assignment.ID,
			TransportMode: agent.TransportMode,
			Payload:       payload,
			AvailableAt:   now,
			ExpireAt:      now.Add(defaultAssignCommandTTL),
		}); err != nil {
			return err
		}

		if err := store.Append(ctx, OutboxEvent{
			Topic:          AssignTaskOutboxTopic,
			AggregateID:    runtimeTask.ID.String(),
			IdempotencyKey: assignTaskOutboxIdempotencyKey(runtimeTask.CurrentExecutionID),
			Payload:        payload,
		}); err != nil {
			return err
		}

		assigned = &AssignResult{
			TaskID:       runtimeTask.ID,
			AssignmentID: assignment.ID,
			ExecutionID:  runtimeTask.CurrentExecutionID,
			AgentID:      runtimeTask.AssignedAgentID,
		}
		return nil
	}); err != nil {
		return nil, err
	}

	return assigned, nil
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

func normalizedResolvedParams(raw []byte) json.RawMessage {
	if len(raw) == 0 {
		return json.RawMessage(`{}`)
	}
	return json.RawMessage(append([]byte(nil), raw...))
}

func assignTaskOutboxIdempotencyKey(executionID string) string {
	return fmt.Sprintf("%s:%s", AssignTaskOutboxTopic, executionID)
}

func newAssignExecutionID() string {
	return strings.ReplaceAll(uuid.NewString(), "-", "")
}

type inlineAssignTaskTxRunner struct {
	store AssignTaskTx
}

func (r inlineAssignTaskTxRunner) InTx(_ context.Context, fn func(store AssignTaskTx) error) error {
	return fn(r.store)
}
