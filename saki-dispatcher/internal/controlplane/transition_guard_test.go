package controlplane

import (
	"testing"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func TestCanStepTransitionRejectsTerminalRollback(t *testing.T) {
	if canStepTransition(db.StepstatusCANCELLED, db.StepstatusRUNNING) {
		t.Fatal("terminal step status should not transition back to RUNNING")
	}
	if canStepTransition(db.StepstatusSUCCEEDED, db.StepstatusREADY) {
		t.Fatal("SUCCEEDED step should not transition back to READY")
	}
}

func TestCanStepTransitionAllowsReadyDispatchingAndRunning(t *testing.T) {
	if !canStepTransition(db.StepstatusREADY, db.StepstatusDISPATCHING) {
		t.Fatal("READY -> DISPATCHING should be allowed")
	}
	if !canStepTransition(db.StepstatusDISPATCHING, db.StepstatusRUNNING) {
		t.Fatal("DISPATCHING -> RUNNING should be allowed")
	}
}

func TestCanLoopTransitionMatrix(t *testing.T) {
	if !canLoopTransition(db.LoopstatusPAUSED, db.LoopstatusRUNNING) {
		t.Fatal("PAUSED -> RUNNING should be allowed")
	}
	if canLoopTransition(db.LoopstatusCOMPLETED, db.LoopstatusRUNNING) {
		t.Fatal("COMPLETED -> RUNNING should not be allowed")
	}
}

func TestDispatchOutboxRetryBackoffCapsAtSixtySeconds(t *testing.T) {
	if got := dispatchOutboxRetryBackoff(1); got.Seconds() != 1 {
		t.Fatalf("attempt=1 expected 1s got=%s", got)
	}
	if got := dispatchOutboxRetryBackoff(3); got.Seconds() != 4 {
		t.Fatalf("attempt=3 expected 4s got=%s", got)
	}
	if got := dispatchOutboxRetryBackoff(10); got.Seconds() != 60 {
		t.Fatalf("attempt=10 expected 60s cap got=%s", got)
	}
}
