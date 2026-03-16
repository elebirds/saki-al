package commands

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/state"
)

func TestCancelTaskCommandCancelsTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &cancelTaskStore{
		task: &TaskRecord{
			ID:          taskID,
			Status:      string(state.TaskStatusRunning),
			ClaimedBy:   "runtime-1",
			LeaderEpoch: 7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewCancelTaskHandler(taskStore, outbox)
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
	if outbox.last == nil || outbox.last.Topic != "runtime.task.canceled" {
		t.Fatalf("expected runtime.task.canceled outbox event, got %+v", outbox.last)
	}
}

type cancelTaskStore struct {
	task    *TaskRecord
	updated *TaskUpdate
}

func (f *cancelTaskStore) GetTask(_ context.Context, _ uuid.UUID) (*TaskRecord, error) {
	return f.task, nil
}

func (f *cancelTaskStore) UpdateTask(_ context.Context, update TaskUpdate) error {
	f.updated = &update
	return nil
}
