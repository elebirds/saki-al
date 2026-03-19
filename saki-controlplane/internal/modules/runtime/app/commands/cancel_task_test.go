package commands

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

func TestCancelTaskCommandRequestsCancelForRunningTaskAndAppendsCancelCommand(t *testing.T) {
	taskID := uuid.New()
	taskStore := &cancelTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusRunning),
			CurrentExecutionID: "exec-running-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
		assignment: &TaskAssignmentRecord{
			ID:          41,
			TaskID:      taskID,
			Attempt:     1,
			AgentID:     "agent-1",
			ExecutionID: "exec-running-1",
			Status:      "running",
		},
		agent: &AgentRecord{
			ID:            "agent-1",
			TransportMode: "pull",
		},
	}
	handler := NewCancelTaskHandler(taskStore)
	handler.now = func() time.Time { return time.Unix(1700000100, 0).UTC() }
	canceled, err := handler.Handle(context.Background(), CancelTaskCommand{TaskID: taskID})
	if err != nil {
		t.Fatalf("handle cancel task: %v", err)
	}

	if canceled == nil || canceled.ID != taskID || canceled.Status != string(state.TaskStatusCancelRequested) {
		t.Fatalf("unexpected canceled task: %+v", canceled)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusCancelRequested) {
		t.Fatalf("expected cancel_requested status update, got %+v", taskStore.updated)
	}
	if taskStore.cancelCommand == nil {
		t.Fatal("expected cancel command append")
	}
	if taskStore.cancelCommand.AssignmentID != 41 || taskStore.cancelCommand.TransportMode != "pull" {
		t.Fatalf("unexpected cancel command params: %+v", taskStore.cancelCommand)
	}
	var payload StopTaskCommandPayload
	if err := json.Unmarshal(taskStore.cancelCommand.Payload, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID || payload.ExecutionID != "exec-running-1" || payload.AgentID != "agent-1" || payload.Reason != "cancel_requested" || payload.LeaderEpoch != 7 {
		t.Fatalf("unexpected stop payload: %+v", payload)
	}
}

func TestCancelTaskCommandRequestsCancelForAssignedTaskAndAppendsCancelCommand(t *testing.T) {
	taskID := uuid.New()
	taskStore := &cancelTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusAssigned),
			CurrentExecutionID: "exec-assigned-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
		assignment: &TaskAssignmentRecord{
			ID:          51,
			TaskID:      taskID,
			Attempt:     1,
			AgentID:     "agent-1",
			ExecutionID: "exec-assigned-1",
			Status:      "assigned",
		},
		agent: &AgentRecord{
			ID:            "agent-1",
			TransportMode: "direct",
		},
	}
	handler := NewCancelTaskHandler(taskStore)
	handler.now = func() time.Time { return time.Unix(1700000000, 0).UTC() }
	canceled, err := handler.Handle(context.Background(), CancelTaskCommand{TaskID: taskID})
	if err != nil {
		t.Fatalf("handle cancel task: %v", err)
	}

	if canceled == nil || canceled.ID != taskID || canceled.Status != string(state.TaskStatusCancelRequested) {
		t.Fatalf("unexpected canceled task: %+v", canceled)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusCancelRequested) {
		t.Fatalf("expected cancel_requested status update, got %+v", taskStore.updated)
	}
	if taskStore.cancelCommand == nil {
		t.Fatal("expected cancel command append")
	}
	if taskStore.cancelCommand.AgentID != "agent-1" || taskStore.cancelCommand.AssignmentID != 51 || taskStore.cancelCommand.TransportMode != "direct" {
		t.Fatalf("unexpected cancel command params: %+v", taskStore.cancelCommand)
	}
	var payload StopTaskCommandPayload
	if err := json.Unmarshal(taskStore.cancelCommand.Payload, &payload); err != nil {
		t.Fatalf("unmarshal stop payload: %v", err)
	}
	if payload.TaskID != taskID || payload.ExecutionID != "exec-assigned-1" || payload.AgentID != "agent-1" || payload.Reason != "cancel_requested" || payload.LeaderEpoch != 7 {
		t.Fatalf("unexpected stop payload: %+v", payload)
	}
}

func TestCancelTaskCommandRejectsAssignedTaskWithoutAssignmentTarget(t *testing.T) {
	taskID := uuid.New()
	taskStore := &cancelTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusAssigned),
			CurrentExecutionID: "exec-assigned-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
	}
	handler := NewCancelTaskHandler(taskStore)

	canceled, err := handler.Handle(context.Background(), CancelTaskCommand{TaskID: taskID})
	if !errors.Is(err, errCancelTaskCommandTargetMissing) {
		t.Fatalf("expected missing target error, got %v", err)
	}
	if canceled != nil {
		t.Fatalf("expected nil canceled task on error, got %+v", canceled)
	}
}

func TestCancelTaskCommandCancelsPendingTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &cancelTaskStore{
		task: &TaskRecord{
			ID:              taskID,
			Status:          string(state.TaskStatusPending),
			AssignedAgentID: "agent-1",
			LeaderEpoch:     7,
		},
	}
	handler := NewCancelTaskHandler(taskStore)
	canceled, err := handler.Handle(context.Background(), CancelTaskCommand{TaskID: taskID})
	if err != nil {
		t.Fatalf("handle cancel task: %v", err)
	}

	if canceled == nil || canceled.ID != taskID || canceled.Status != string(state.TaskStatusCanceled) {
		t.Fatalf("unexpected canceled task: %+v", canceled)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusCanceled) {
		t.Fatalf("expected canceled status update, got %+v", taskStore.updated)
	}
	if taskStore.cancelCommand != nil {
		t.Fatalf("expected no cancel command for direct pending cancel, got %+v", taskStore.cancelCommand)
	}
}

type cancelTaskStore struct {
	task          *TaskRecord
	assignment    *TaskAssignmentRecord
	agent         *AgentRecord
	updated       *TaskUpdate
	cancelCommand *AppendCancelTaskCommandParams
}

func (f *cancelTaskStore) GetTask(_ context.Context, _ uuid.UUID) (*TaskRecord, error) {
	return f.task, nil
}

func (f *cancelTaskStore) UpdateTask(_ context.Context, update TaskUpdate) error {
	f.updated = &update
	return nil
}

func (f *cancelTaskStore) GetTaskAssignmentByExecutionID(_ context.Context, executionID string) (*TaskAssignmentRecord, error) {
	if f.assignment == nil || f.assignment.ExecutionID != executionID {
		return nil, nil
	}
	return f.assignment, nil
}

func (f *cancelTaskStore) GetAgentByID(_ context.Context, agentID string) (*AgentRecord, error) {
	if f.agent == nil || f.agent.ID != agentID {
		return nil, nil
	}
	return f.agent, nil
}

func (f *cancelTaskStore) AppendCancelCommand(_ context.Context, params AppendCancelTaskCommandParams) error {
	f.cancelCommand = &params
	return nil
}
