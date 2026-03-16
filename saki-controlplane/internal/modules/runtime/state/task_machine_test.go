package state

import (
	"errors"
	"testing"
)

func TestTaskMachine_StartPendingTask(t *testing.T) {
	snapshot := TaskSnapshot{Status: TaskStatusPending}

	events, err := DecideTask(snapshot, StartTask{})
	if err != nil {
		t.Fatalf("decide start task: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one event, got %d", len(events))
	}

	next := snapshot
	for _, event := range events {
		next = EvolveTask(next, event)
	}

	if next.Status != TaskStatusRunning {
		t.Fatalf("expected running task, got %s", next.Status)
	}
}

func TestTaskMachine_RejectFinishFromPending(t *testing.T) {
	_, err := DecideTask(TaskSnapshot{Status: TaskStatusPending}, FinishTask{})
	if !errors.Is(err, ErrInvalidTransition) {
		t.Fatalf("expected invalid transition, got %v", err)
	}
}
