package controlplane

import (
	"reflect"
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

func TestToRuntimeStepType(t *testing.T) {
	cases := map[db.Steptype]runtimecontrolv1.RuntimeStepType{
		db.SteptypeTRAIN:           runtimecontrolv1.RuntimeStepType_TRAIN,
		db.SteptypeSCORE:           runtimecontrolv1.RuntimeStepType_SCORE,
		db.SteptypeSELECT:          runtimecontrolv1.RuntimeStepType_SELECT,
		db.SteptypeACTIVATESAMPLES: runtimecontrolv1.RuntimeStepType_ACTIVATE_SAMPLES,
		db.SteptypeADVANCEBRANCH:   runtimecontrolv1.RuntimeStepType_ADVANCE_BRANCH,
		db.SteptypeEVAL:            runtimecontrolv1.RuntimeStepType_EVAL,
		db.SteptypeUPLOADARTIFACT:  runtimecontrolv1.RuntimeStepType_UPLOAD_ARTIFACT,
		db.SteptypeEXPORT:          runtimecontrolv1.RuntimeStepType_EXPORT,
		db.SteptypeCUSTOM:          runtimecontrolv1.RuntimeStepType_CUSTOM,
	}
	for stepType, want := range cases {
		if got := toRuntimeStepType(stepType); got != want {
			t.Fatalf("step type mapping mismatch: %s -> %v, want %v", stepType, got, want)
		}
	}
	if got := toRuntimeStepType(db.Steptype("UNKNOWN")); got != runtimecontrolv1.RuntimeStepType_RUNTIME_STEP_TYPE_UNSPECIFIED {
		t.Fatalf("unknown step type fallback mismatch: %v", got)
	}
}

func TestStepPlanByModeDispatchKinds(t *testing.T) {
	plan := stepPlanByMode(modeSIM)
	if len(plan) != 6 {
		t.Fatalf("simulation step plan size mismatch: %d", len(plan))
	}
	last := plan[len(plan)-1]
	if last.StepType != db.SteptypeADVANCEBRANCH {
		t.Fatalf("last sim step mismatch: %s", last.StepType)
	}
	if last.DispatchKind != db.StepdispatchkindORCHESTRATOR {
		t.Fatalf("last sim step dispatch kind mismatch: %s", last.DispatchKind)
	}

	manualPlan := stepPlanByMode(modeManual)
	if len(manualPlan) != 3 {
		t.Fatalf("manual step plan size mismatch: %d", len(manualPlan))
	}
	for _, item := range manualPlan {
		if item.DispatchKind != db.StepdispatchkindDISPATCHABLE {
			t.Fatalf("manual step should be dispatchable: %s => %s", item.StepType, item.DispatchKind)
		}
	}
}

func TestPhaseForStep(t *testing.T) {
	if phase, ok := phaseForStep(modeSIM, db.SteptypeADVANCEBRANCH); !ok || phase != phaseSimActivate {
		t.Fatalf("phase mapping mismatch for SIM advance_branch: ok=%v phase=%s", ok, phase)
	}
	if _, ok := phaseForStep(modeManual, db.SteptypeCUSTOM); ok {
		t.Fatal("manual CUSTOM should not have default phase mapping")
	}
	if _, ok := phaseForStep(modeAL, db.Steptype("LEGACY_STEP")); ok {
		t.Fatal("unknown step type should not have phase mapping")
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

func TestShouldApplyRuntimeStatus(t *testing.T) {
	if shouldApplyRuntimeStatus(db.Stepstatus("")) {
		t.Fatal("empty runtime status should be ignored")
	}
	if shouldApplyRuntimeStatus(db.StepstatusPENDING) {
		t.Fatal("runtime PENDING status should be ignored")
	}
	if !shouldApplyRuntimeStatus(db.StepstatusRUNNING) {
		t.Fatal("runtime RUNNING status should be applied")
	}
}

func TestCanLoopLifecycleTransitionMatrix(t *testing.T) {
	if !canLoopLifecycleTransition(db.LooplifecyclePAUSED, db.LooplifecycleRUNNING) {
		t.Fatal("PAUSED -> RUNNING should be allowed")
	}
	if canLoopLifecycleTransition(db.LooplifecycleCOMPLETED, db.LooplifecycleRUNNING) {
		t.Fatal("COMPLETED -> RUNNING should not be allowed")
	}
	if canLoopLifecycleTransition(db.LooplifecycleSTOPPED, db.LooplifecycleRUNNING) {
		t.Fatal("STOPPED -> RUNNING should not be allowed")
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

func TestStepStatusCountsForAPINormalizesToLowercase(t *testing.T) {
	counts := map[db.Stepstatus]int{
		db.StepstatusSUCCEEDED:     4,
		db.StepstatusRUNNING:       1,
		db.Stepstatus("succeeded"): 2,
		db.Stepstatus(" "):         7,
	}
	got := stepStatusCountsForAPI(counts)
	want := map[string]int{
		"succeeded": 6,
		"running":   1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("step status counts normalization mismatch: got=%v want=%v", got, want)
	}
}
