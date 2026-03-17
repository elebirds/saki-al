package state

import (
	"errors"
	"testing"
)

func TestTaskMachine_AssignPendingTask(t *testing.T) {
	snapshot := TaskSnapshot{Status: TaskStatusPending}

	events, err := DecideTask(snapshot, AssignTask{})
	if err != nil {
		t.Fatalf("decide assign task: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one event, got %d", len(events))
	}

	next := snapshot
	for _, event := range events {
		next = EvolveTask(next, event)
	}

	if next.Status != TaskStatusAssigned {
		t.Fatalf("expected assigned task, got %s", next.Status)
	}
}

func TestTaskMachine_StartAssignedTask(t *testing.T) {
	snapshot := TaskSnapshot{Status: TaskStatusAssigned}

	events, err := DecideTask(snapshot, StartTaskExecution{})
	if err != nil {
		t.Fatalf("decide start task execution: %v", err)
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

func TestTaskMachine_RequestCancelRunningTask(t *testing.T) {
	snapshot := TaskSnapshot{Status: TaskStatusRunning}

	events, err := DecideTask(snapshot, RequestTaskCancel{})
	if err != nil {
		t.Fatalf("decide request cancel task: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one event, got %d", len(events))
	}

	next := snapshot
	for _, event := range events {
		next = EvolveTask(next, event)
	}

	if next.Status != TaskStatusCancelRequested {
		t.Fatalf("expected cancel_requested task, got %s", next.Status)
	}
}

func TestTaskMachine_RejectFinishFromAssigned(t *testing.T) {
	_, err := DecideTask(TaskSnapshot{Status: TaskStatusAssigned}, FinishTask{})
	if !errors.Is(err, ErrInvalidTransition) {
		t.Fatalf("expected invalid transition, got %v", err)
	}
}
