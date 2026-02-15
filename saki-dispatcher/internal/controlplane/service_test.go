package controlplane

import (
	"testing"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func TestActivationCommandIDIsDeterministic(t *testing.T) {
	stepPayload := stepDispatchPayload{
		LoopID:        "5f9cc0b9-5605-45f9-ab99-57e099a14d77",
		RoundIndex:    3,
		StepID:        "b7b947e9-9985-4637-ae6e-8812d78cbe3d",
		Attempt:       2,
		InputCommitID: "afdc1e09-7fd4-4ef6-909f-87a406f5da8f",
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
		LoopID:        "5f9cc0b9-5605-45f9-ab99-57e099a14d77",
		RoundIndex:    3,
		StepID:        "b7b947e9-9985-4637-ae6e-8812d78cbe3d",
		Attempt:       1,
		InputCommitID: "afdc1e09-7fd4-4ef6-909f-87a406f5da8f",
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
		LoopID:        "5f9cc0b9-5605-45f9-ab99-57e099a14d77",
		RoundIndex:    3,
		StepID:        "b7b947e9-9985-4637-ae6e-8812d78cbe3d",
		Attempt:       2,
		InputCommitID: "afdc1e09-7fd4-4ef6-909f-87a406f5da8f",
	}
	const want = "activate_samples:096bfc91a1c3db5e98c4b00f9d21abe2bbd9951a02f173e59eb2a0ff2f7cc3df"
	if got := activationCommandID(stepPayload); got != want {
		t.Fatalf("activation command id vector mismatch: got=%q want=%q", got, want)
	}
}

func TestCancelAttemptCommandIDIsDeterministicAndAttemptScoped(t *testing.T) {
	base := cancelAttemptCommandID("a03fbb75-c393-45d9-abab-76f3272f06fc", 1)
	if base == "" {
		t.Fatal("cancel attempt command id should not be empty")
	}
	again := cancelAttemptCommandID("a03fbb75-c393-45d9-abab-76f3272f06fc", 1)
	if base != again {
		t.Fatalf("cancel attempt command id should be deterministic: %q != %q", base, again)
	}
	next := cancelAttemptCommandID("a03fbb75-c393-45d9-abab-76f3272f06fc", 2)
	if base == next {
		t.Fatalf("cancel attempt command id should include attempt dimension: %q", base)
	}
}

func TestToRuntimeStepDispatchKind(t *testing.T) {
	if got := toRuntimeStepDispatchKind("dispatchable"); got != runtimecontrolv1.RuntimeStepDispatchKind_DISPATCHABLE {
		t.Fatalf("dispatchable mapping mismatch: %v", got)
	}
	if got := toRuntimeStepDispatchKind("orchestrator"); got != runtimecontrolv1.RuntimeStepDispatchKind_ORCHESTRATOR {
		t.Fatalf("orchestrator mapping mismatch: %v", got)
	}
	if got := toRuntimeStepDispatchKind("unknown"); got != runtimecontrolv1.RuntimeStepDispatchKind_RUNTIME_STEP_DISPATCH_KIND_UNSPECIFIED {
		t.Fatalf("unexpected fallback mapping: %v", got)
	}
}

func TestIsOrchestratorDispatchKind(t *testing.T) {
	if !isOrchestratorDispatchKind("ORCHESTRATOR") {
		t.Fatal("ORCHESTRATOR should be recognized as orchestrator dispatch kind")
	}
	if isOrchestratorDispatchKind("DISPATCHABLE") {
		t.Fatal("DISPATCHABLE should not be recognized as orchestrator dispatch kind")
	}
}
