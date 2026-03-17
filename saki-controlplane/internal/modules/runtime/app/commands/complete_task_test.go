package commands

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

func TestCompleteTaskCommandCompletesRunningTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &completeTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusRunning),
			CurrentExecutionID: "exec-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewCompleteTaskHandler(taskStore, outbox)
	completed, err := handler.Handle(context.Background(), CompleteTaskCommand{
		TaskID:      taskID,
		ExecutionID: "exec-1",
	})
	if err != nil {
		t.Fatalf("handle complete task: %v", err)
	}

	if completed == nil || completed.ID != taskID || completed.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("unexpected completed task: %+v", completed)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("expected succeeded status update, got %+v", taskStore.updated)
	}
	if outbox.last == nil || outbox.last.Topic != "runtime.task.completed" {
		t.Fatalf("expected runtime.task.completed outbox event, got %+v", outbox.last)
	}
}

func TestCompleteTaskCommandRejectsAssignedTask(t *testing.T) {
	taskID := uuid.New()
	taskStore := &completeTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusAssigned),
			CurrentExecutionID: "exec-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewCompleteTaskHandler(taskStore, outbox)
	completed, err := handler.Handle(context.Background(), CompleteTaskCommand{
		TaskID:      taskID,
		ExecutionID: "exec-1",
	})
	if !errors.Is(err, state.ErrInvalidTransition) {
		t.Fatalf("expected invalid transition, got %v", err)
	}
	if completed != nil {
		t.Fatalf("expected nil completed task, got %+v", completed)
	}
	if taskStore.updated != nil {
		t.Fatalf("did not expect task update on invalid transition, got %+v", taskStore.updated)
	}
	if outbox.last != nil {
		t.Fatalf("did not expect outbox event on invalid transition, got %+v", outbox.last)
	}
}

func TestCompleteTaskCommandCompletesCancelRequestedTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &completeTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusCancelRequested),
			CurrentExecutionID: "exec-1",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewCompleteTaskHandler(taskStore, outbox)
	completed, err := handler.Handle(context.Background(), CompleteTaskCommand{
		TaskID:      taskID,
		ExecutionID: "exec-1",
	})
	if err != nil {
		t.Fatalf("handle complete task: %v", err)
	}
	if completed == nil || completed.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("unexpected completed task: %+v", completed)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusSucceeded) {
		t.Fatalf("expected succeeded update, got %+v", taskStore.updated)
	}
	if outbox.last == nil || outbox.last.Topic != "runtime.task.completed" {
		t.Fatalf("expected runtime.task.completed outbox event, got %+v", outbox.last)
	}
}

func TestCompleteTaskCommandIgnoresStaleExecutionID(t *testing.T) {
	taskID := uuid.New()
	taskStore := &completeTaskStore{
		task: &TaskRecord{
			ID:                 taskID,
			Status:             string(state.TaskStatusRunning),
			CurrentExecutionID: "exec-current",
			AssignedAgentID:    "agent-1",
			LeaderEpoch:        7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewCompleteTaskHandler(taskStore, outbox)
	completed, err := handler.Handle(context.Background(), CompleteTaskCommand{
		TaskID:      taskID,
		ExecutionID: "exec-stale",
	})
	if err != nil {
		t.Fatalf("handle stale complete task: %v", err)
	}
	if completed != nil {
		t.Fatalf("expected stale execution to be ignored, got %+v", completed)
	}
	if taskStore.updated != nil {
		t.Fatalf("did not expect update for stale execution, got %+v", taskStore.updated)
	}
	if outbox.last != nil {
		t.Fatalf("did not expect outbox for stale execution, got %+v", outbox.last)
	}
}

type completeTaskStore struct {
	task    *TaskRecord
	updated *TaskUpdate
}

func (f *completeTaskStore) GetTask(_ context.Context, _ uuid.UUID) (*TaskRecord, error) {
	return f.task, nil
}

func (f *completeTaskStore) AdvanceTaskByExecution(_ context.Context, params AdvanceTaskByExecutionParams) (*TaskRecord, error) {
	if f.task == nil {
		return nil, nil
	}
	if f.task.CurrentExecutionID != params.ExecutionID {
		return nil, nil
	}
	if !slices.Contains(params.FromStatuses, f.task.Status) {
		return nil, nil
	}

	f.task.Status = params.ToStatus
	f.updated = &TaskUpdate{
		ID:              f.task.ID,
		Status:          f.task.Status,
		AssignedAgentID: f.task.AssignedAgentID,
		LeaderEpoch:     f.task.LeaderEpoch,
	}
	copied := *f.task
	return &copied, nil
}
