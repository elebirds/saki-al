package commands

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

func TestAssignTaskCommandClaimsPendingTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &fakeTaskStore{
		nextTask: &TaskRecord{
			ID:     taskID,
			Status: string(state.TaskStatusPending),
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewAssignTaskHandler(taskStore, outbox)
	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		ClaimedBy:   "runtime-1",
		LeaderEpoch: 7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}

	if assigned == nil || assigned.ID != taskID {
		t.Fatalf("unexpected assigned task: %+v", assigned)
	}
	if taskStore.updated == nil || taskStore.updated.Status != string(state.TaskStatusAssigned) {
		t.Fatalf("expected assigned status update, got %+v", taskStore.updated)
	}
	if outbox.last == nil || outbox.last.Topic != "runtime.task.assigned" {
		t.Fatalf("expected runtime.task.assigned outbox event, got %+v", outbox.last)
	}
}

type fakeTaskStore struct {
	nextTask *TaskRecord
	updated  *TaskUpdate
}

func (f *fakeTaskStore) NextPendingTask(context.Context) (*TaskRecord, error) {
	return f.nextTask, nil
}

func (f *fakeTaskStore) UpdateTask(_ context.Context, update TaskUpdate) error {
	f.updated = &update
	return nil
}

type fakeOutboxWriter struct {
	last *OutboxEvent
}

func (f *fakeOutboxWriter) Append(_ context.Context, event OutboxEvent) error {
	f.last = &event
	return nil
}
