package controlplane

import (
	"testing"

	"github.com/google/uuid"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func mustUUID(raw string) uuid.UUID {
	id, err := uuid.Parse(raw)
	if err != nil {
		panic(err)
	}
	return id
}

func mustUUIDPtr(raw string) *uuid.UUID {
	id := mustUUID(raw)
	return &id
}

func TestActivationCommandIDIsDeterministic(t *testing.T) {
	stepPayload := stepDispatchPayload{
		LoopID:        mustUUID("5f9cc0b9-5605-45f9-ab99-57e099a14d77"),
		RoundIndex:    3,
		StepID:        mustUUID("b7b947e9-9985-4637-ae6e-8812d78cbe3d"),
		Attempt:       2,
		InputCommitID: mustUUIDPtr("afdc1e09-7fd4-4ef6-909f-87a406f5da8f"),
	}

	first := activationCommandID(stepPayload)
	second := activationCommandID(stepPayload)
	if first == "" {
		t.Fatal("activation command id should not be empty")
	}
	if first != second {
		t.Fatalf("activation command id should be deterministic: %q != %q", first, second)
	}
}

func TestActivationCommandIDChangesWhenAttemptChanges(t *testing.T) {
	stepPayload := stepDispatchPayload{
		LoopID:        mustUUID("5f9cc0b9-5605-45f9-ab99-57e099a14d77"),
		RoundIndex:    3,
		StepID:        mustUUID("b7b947e9-9985-4637-ae6e-8812d78cbe3d"),
		Attempt:       1,
		InputCommitID: mustUUIDPtr("afdc1e09-7fd4-4ef6-909f-87a406f5da8f"),
	}
	one := activationCommandID(stepPayload)
	stepPayload.Attempt = 2
	two := activationCommandID(stepPayload)
	if one == two {
		t.Fatalf("activation command id should change when attempt changes: %q", one)
	}
}

func TestActivationCommandIDMatchesFixedVector(t *testing.T) {
	stepPayload := stepDispatchPayload{
		LoopID:        mustUUID("5f9cc0b9-5605-45f9-ab99-57e099a14d77"),
		RoundIndex:    3,
		StepID:        mustUUID("b7b947e9-9985-4637-ae6e-8812d78cbe3d"),
		Attempt:       2,
		InputCommitID: mustUUIDPtr("afdc1e09-7fd4-4ef6-909f-87a406f5da8f"),
	}
	const want = "activate_samples:096bfc91a1c3db5e98c4b00f9d21abe2bbd9951a02f173e59eb2a0ff2f7cc3df"
	if got := activationCommandID(stepPayload); got != want {
		t.Fatalf("activation command id vector mismatch: got=%q want=%q", got, want)
	}
}

func TestCancelAttemptCommandIDIsDeterministicAndAttemptScoped(t *testing.T) {
	base := cancelAttemptCommandID(mustUUID("a03fbb75-c393-45d9-abab-76f3272f06fc"), 1)
	if base == "" {
		t.Fatal("cancel attempt command id should not be empty")
	}
	again := cancelAttemptCommandID(mustUUID("a03fbb75-c393-45d9-abab-76f3272f06fc"), 1)
	if base != again {
		t.Fatalf("cancel attempt command id should be deterministic: %q != %q", base, again)
	}
	next := cancelAttemptCommandID(mustUUID("a03fbb75-c393-45d9-abab-76f3272f06fc"), 2)
	if base == next {
		t.Fatalf("cancel attempt command id should include attempt dimension: %q", base)
	}
}

func TestToRuntimeStepDispatchKind(t *testing.T) {
	if got := toRuntimeStepDispatchKind(db.StepdispatchkindDISPATCHABLE); got != runtimecontrolv1.RuntimeStepDispatchKind_DISPATCHABLE {
		t.Fatalf("dispatchable mapping mismatch: %v", got)
	}
	if got := toRuntimeStepDispatchKind(db.StepdispatchkindORCHESTRATOR); got != runtimecontrolv1.RuntimeStepDispatchKind_ORCHESTRATOR {
		t.Fatalf("orchestrator mapping mismatch: %v", got)
	}
	if got := toRuntimeStepDispatchKind(db.Stepdispatchkind("unknown")); got != runtimecontrolv1.RuntimeStepDispatchKind_RUNTIME_STEP_DISPATCH_KIND_UNSPECIFIED {
		t.Fatalf("unexpected fallback mapping: %v", got)
	}
}

func TestIsOrchestratorDispatchKind(t *testing.T) {
	if !isOrchestratorDispatchKind(db.StepdispatchkindORCHESTRATOR) {
		t.Fatal("ORCHESTRATOR should be recognized as orchestrator dispatch kind")
	}
	if isOrchestratorDispatchKind(db.StepdispatchkindDISPATCHABLE) {
		t.Fatal("DISPATCHABLE should not be recognized as orchestrator dispatch kind")
	}
}
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
