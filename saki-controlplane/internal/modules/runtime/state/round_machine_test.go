package state

import (
	"errors"
	"testing"
)

func TestRoundMachine_StartPendingRound(t *testing.T) {
	snapshot := RoundSnapshot{Status: RoundStatusPending}

	events, err := DecideRound(snapshot, StartRound{})
	if err != nil {
		t.Fatalf("decide start round: %v", err)
	}

	next := snapshot
	for _, event := range events {
		next = EvolveRound(next, event)
	}

	if next.Status != RoundStatusActive {
		t.Fatalf("expected active round, got %s", next.Status)
	}
}

func TestRoundMachine_RejectCompleteFromPending(t *testing.T) {
	_, err := DecideRound(RoundSnapshot{Status: RoundStatusPending}, CompleteRound{})
	if !errors.Is(err, ErrInvalidTransition) {
		t.Fatalf("expected invalid transition, got %v", err)
	}
}
