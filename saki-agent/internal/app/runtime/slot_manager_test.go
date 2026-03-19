package runtime

import (
	"errors"
	"testing"
)

func TestSlotManagerAdmitsUntilLimit(t *testing.T) {
	manager := NewSlotManager(2)

	if err := manager.Admit(&activeExecution{taskID: "task-1", executionID: "exec-1"}); err != nil {
		t.Fatalf("admit first execution: %v", err)
	}
	if err := manager.Admit(&activeExecution{taskID: "task-2", executionID: "exec-2"}); err != nil {
		t.Fatalf("admit second execution: %v", err)
	}

	if got := manager.RunningTaskIDs(); len(got) != 2 {
		t.Fatalf("expected two running tasks, got %v", got)
	}
}

func TestSlotManagerRejectsWhenAllSlotsBusy(t *testing.T) {
	manager := NewSlotManager(1)

	if err := manager.Admit(&activeExecution{taskID: "task-1", executionID: "exec-1"}); err != nil {
		t.Fatalf("admit first execution: %v", err)
	}

	err := manager.Admit(&activeExecution{taskID: "task-2", executionID: "exec-2"})
	if !errors.Is(err, errAgentBusy) {
		t.Fatalf("expected busy error, got %v", err)
	}
}

func TestSlotManagerCancelsMatchingExecutionOnly(t *testing.T) {
	cancelled := false
	manager := NewSlotManager(2)

	if err := manager.Admit(&activeExecution{
		taskID:      "task-1",
		executionID: "exec-1",
		cancel: func() {
			cancelled = true
		},
	}); err != nil {
		t.Fatalf("admit execution: %v", err)
	}

	if manager.Cancel("task-1", "exec-2") {
		t.Fatal("expected mismatched execution to be ignored")
	}
	if cancelled {
		t.Fatal("expected mismatched cancel to avoid cancel callback")
	}
	if !manager.Cancel("task-1", "exec-1") {
		t.Fatal("expected matching execution to be canceled")
	}
	if !cancelled {
		t.Fatal("expected matching cancel to call cancel callback")
	}
}
