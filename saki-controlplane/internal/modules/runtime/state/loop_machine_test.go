package state

import (
	"errors"
	"testing"
)

func TestLoopMachine_StartDraftLoop(t *testing.T) {
	snapshot := LoopSnapshot{Status: LoopStatusDraft}

	events, err := DecideLoop(snapshot, StartLoop{})
	if err != nil {
		t.Fatalf("decide start loop: %v", err)
	}

	next := snapshot
	for _, event := range events {
		next = EvolveLoop(next, event)
	}

	if next.Status != LoopStatusActive {
		t.Fatalf("expected active loop, got %s", next.Status)
	}
}

func TestLoopMachine_RejectCompleteFromDraft(t *testing.T) {
	_, err := DecideLoop(LoopSnapshot{Status: LoopStatusDraft}, CompleteLoop{})
	if !errors.Is(err, ErrInvalidTransition) {
		t.Fatalf("expected invalid transition, got %v", err)
	}
}
