package controlplane

import (
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/spf13/cast"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
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

func TestToRuntimeTaskDispatchKind(t *testing.T) {
	if got := toRuntimeTaskDispatchKind(db.StepdispatchkindDISPATCHABLE); got != runtimecontrolv1.RuntimeTaskDispatchKind_DISPATCHABLE {
		t.Fatalf("dispatchable mapping mismatch: %v", got)
	}
	if got := toRuntimeTaskDispatchKind(db.StepdispatchkindORCHESTRATOR); got != runtimecontrolv1.RuntimeTaskDispatchKind_ORCHESTRATOR {
		t.Fatalf("orchestrator mapping mismatch: %v", got)
	}
	if got := toRuntimeTaskDispatchKind(db.Stepdispatchkind("unknown")); got != runtimecontrolv1.RuntimeTaskDispatchKind_RUNTIME_TASK_DISPATCH_KIND_UNSPECIFIED {
		t.Fatalf("unexpected fallback mapping: %v", got)
	}
}

func TestToRuntimeTaskType(t *testing.T) {
	cases := map[db.Steptype]runtimecontrolv1.RuntimeTaskType{
		db.SteptypeTRAIN:  runtimecontrolv1.RuntimeTaskType_TRAIN,
		db.SteptypeSCORE:  runtimecontrolv1.RuntimeTaskType_SCORE,
		db.SteptypeSELECT: runtimecontrolv1.RuntimeTaskType_SELECT,
		db.SteptypeEVAL:   runtimecontrolv1.RuntimeTaskType_EVAL,
		db.SteptypeCUSTOM: runtimecontrolv1.RuntimeTaskType_CUSTOM,
	}
	for stepType, want := range cases {
		if got := toRuntimeTaskType(stepType); got != want {
			t.Fatalf("step type mapping mismatch: %s -> %v, want %v", stepType, got, want)
		}
	}
	if got := toRuntimeTaskType(db.Steptype("UNKNOWN")); got != runtimecontrolv1.RuntimeTaskType_RUNTIME_TASK_TYPE_UNSPECIFIED {
		t.Fatalf("unknown step type fallback mismatch: %v", got)
	}
}

func TestRuntimeTaskTypeFromTaskType(t *testing.T) {
	cases := map[string]runtimecontrolv1.RuntimeTaskType{
		"TRAIN":   runtimecontrolv1.RuntimeTaskType_TRAIN,
		"EVAL":    runtimecontrolv1.RuntimeTaskType_EVAL,
		"SCORE":   runtimecontrolv1.RuntimeTaskType_SCORE,
		"SELECT":  runtimecontrolv1.RuntimeTaskType_SELECT,
		"PREDICT": runtimecontrolv1.RuntimeTaskType_PREDICT,
		"CUSTOM":  runtimecontrolv1.RuntimeTaskType_CUSTOM,
	}
	for taskType, want := range cases {
		if got := runtimeTaskTypeFromTaskType(taskType); got != want {
			t.Fatalf("task type mapping mismatch: %s -> %v, want %v", taskType, got, want)
		}
	}
	if got := runtimeTaskTypeFromTaskType("legacy"); got != runtimecontrolv1.RuntimeTaskType_RUNTIME_TASK_TYPE_UNSPECIFIED {
		t.Fatalf("unknown task type fallback mismatch: %v", got)
	}
}

func TestResolveTaskPayloadQueryStrategyPredictAlwaysEmpty(t *testing.T) {
	params, err := structpb.NewStruct(map[string]any{
		"sampling": map[string]any{
			"strategy": "uncertainty_1_minus_max_conf",
		},
	})
	if err != nil {
		t.Fatalf("build struct failed: %v", err)
	}
	if got := resolveTaskPayloadQueryStrategy("PREDICT", params); got != "" {
		t.Fatalf("predict query strategy should be empty, got=%q", got)
	}
	if got := resolveTaskPayloadQueryStrategy("score", params); got != "uncertainty_1_minus_max_conf" {
		t.Fatalf("score query strategy mismatch, got=%q", got)
	}
}

func TestIsTaskStatusDispatchable(t *testing.T) {
	dispatchable := []string{
		"PENDING",
		"READY",
		"RETRYING",
	}
	for _, status := range dispatchable {
		if !isTaskStatusDispatchable(status) {
			t.Fatalf("status should be dispatchable: %s", status)
		}
	}

	undispatchable := []string{
		"DISPATCHING",
		"RUNNING",
		"SUCCEEDED",
		"FAILED",
		"SKIPPED",
		"CANCELLED",
		"UNKNOWN",
		"",
	}
	for _, status := range undispatchable {
		if isTaskStatusDispatchable(status) {
			t.Fatalf("status should not be dispatchable: %s", status)
		}
	}
}

func TestStepPlanByModeDispatchKinds(t *testing.T) {
	plan := stepPlanByMode(modeSIM)
	if len(plan) != 4 {
		t.Fatalf("simulation step plan size mismatch: %d", len(plan))
	}
	last := plan[len(plan)-1]
	if last.StepType != db.SteptypeSELECT {
		t.Fatalf("last sim step mismatch: %s", last.StepType)
	}
	if last.DispatchKind != db.StepdispatchkindORCHESTRATOR {
		t.Fatalf("last sim step dispatch kind mismatch: %s", last.DispatchKind)
	}

	manualPlan := stepPlanByMode(modeManual)
	if len(manualPlan) != 2 {
		t.Fatalf("manual step plan size mismatch: %d", len(manualPlan))
	}
	for _, item := range manualPlan {
		if item.DispatchKind != db.StepdispatchkindDISPATCHABLE {
			t.Fatalf("manual step should be dispatchable: %s => %s", item.StepType, item.DispatchKind)
		}
	}
}

func TestPhaseForStep(t *testing.T) {
	if phase, ok := phaseForStep(modeSIM, db.SteptypeSELECT); !ok || phase != phaseSimSelect {
		t.Fatalf("phase mapping mismatch for SIM select: ok=%v phase=%s", ok, phase)
	}
	if _, ok := phaseForStep(modeManual, db.SteptypeCUSTOM); ok {
		t.Fatal("manual CUSTOM should not have default phase mapping")
	}
	if _, ok := phaseForStep(modeAL, db.Steptype("LEGACY_STEP")); ok {
		t.Fatal("unknown step type should not have phase mapping")
	}
}

func TestSimulationFinalizeTrainEnabledStepPlan(t *testing.T) {
	disabled := simulationFinalizeTrainEnabledStepPlan(false)
	if len(disabled) != 0 {
		t.Fatalf("disabled finalize train plan should be empty, got=%d", len(disabled))
	}

	enabled := simulationFinalizeTrainEnabledStepPlan(true)
	if len(enabled) != 2 {
		t.Fatalf("enabled finalize train plan size mismatch: %d", len(enabled))
	}
	if enabled[0].StepType != db.SteptypeTRAIN || enabled[1].StepType != db.SteptypeEVAL {
		t.Fatalf("finalize train plan should be TRAIN->EVAL, got=%s->%s", enabled[0].StepType, enabled[1].StepType)
	}
}

func TestModeRoundPolicyForSupportsAllLoopModes(t *testing.T) {
	service := &Service{}
	cases := []db.Loopmode{modeAL, modeSIM, modeManual}
	for _, mode := range cases {
		policy, err := service.modeRoundPolicyFor(mode)
		if err != nil {
			t.Fatalf("mode %s should resolve policy: %v", mode, err)
		}
		if policy == nil {
			t.Fatalf("mode %s resolved nil policy", mode)
		}
	}
}

func TestModeRoundPolicyForRejectsUnsupportedMode(t *testing.T) {
	service := &Service{}
	if _, err := service.modeRoundPolicyFor(db.Loopmode("legacy")); err == nil {
		t.Fatal("unsupported mode should return error")
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

func TestIsImmediateCancelOnLoopStopping(t *testing.T) {
	cases := []struct {
		status db.Runtimetaskstatus
		want   bool
	}{
		{status: db.RuntimetaskstatusPENDING, want: true},
		{status: db.RuntimetaskstatusREADY, want: true},
		{status: db.RuntimetaskstatusSYNCINGENV, want: true},
		{status: db.RuntimetaskstatusPROBINGRUNTIME, want: true},
		{status: db.RuntimetaskstatusBINDINGDEVICE, want: true},
		{status: db.RuntimetaskstatusDISPATCHING, want: false},
		{status: db.RuntimetaskstatusRUNNING, want: false},
		{status: db.RuntimetaskstatusRETRYING, want: false},
		{status: db.RuntimetaskstatusSUCCEEDED, want: false},
	}
	for _, tc := range cases {
		got := isImmediateCancelOnLoopStopping(tc.status)
		if got != tc.want {
			t.Fatalf("unexpected stopping cancel policy status=%s got=%v want=%v", tc.status, got, tc.want)
		}
	}
}

func TestShouldRequeueDispatchOutbox(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "demo_det_v1")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")

	service := &Service{dispatcher: dispatcher}
	taskID := uuid.New()
	currentExecutionID := uuid.New()

	requeue, reason := service.shouldRequeueDispatchOutbox(db.ListActiveDispatchOutboxRecoveryCandidatesRow{
		ID:                 uuid.New(),
		TaskID:             taskID,
		ExecutorID:         "executor-a",
		LastError:          "executor 不可用或队列已满",
		PluginID:           "demo_det_v1",
		TaskKind:           "STEP",
		TaskStatus:         "DISPATCHING",
		CurrentExecutionID: currentExecutionID,
		AssignedExecutorID: "executor-a",
		ExecutorOnline:     true,
	})
	if !requeue {
		t.Fatal("queue full outbox should be requeued")
	}
	if reason == "" {
		t.Fatal("queue full outbox should carry a reason")
	}

	if err := dispatcher.HandleHeartbeat(&runtimecontrolv1.Heartbeat{
		ExecutorId:    "executor-a",
		Busy:          true,
		CurrentTaskId: "other-task",
	}); err != nil {
		t.Fatalf("mark executor-a busy failed: %v", err)
	}

	requeue, reason = service.shouldRequeueDispatchOutbox(db.ListActiveDispatchOutboxRecoveryCandidatesRow{
		ID:                 uuid.New(),
		TaskID:             taskID,
		ExecutorID:         "executor-a",
		PluginID:           "demo_det_v1",
		TaskKind:           "STEP",
		TaskStatus:         "DISPATCHING",
		CurrentExecutionID: currentExecutionID,
		AssignedExecutorID: "executor-a",
		ExecutorOnline:     true,
	})
	if !requeue {
		t.Fatal("busy executor with available fallback should be requeued")
	}
	if reason == "" {
		t.Fatal("busy executor fallback should carry a reason")
	}
}

func TestCompileRoundConfigSeedsStableAcrossRoundIndex(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790aca"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {"global_seed": "seed-fixed", "deterministic_level": "deterministic"}
		}`),
	}
	first := compileRoundConfig(loop, 1)
	second := compileRoundConfig(loop, 99)

	if first["split_seed"] != second["split_seed"] {
		t.Fatalf("split_seed should be stable across rounds: %v != %v", first["split_seed"], second["split_seed"])
	}
	if first["train_seed"] != second["train_seed"] {
		t.Fatalf("train_seed should be stable across rounds: %v != %v", first["train_seed"], second["train_seed"])
	}
	if first["sampling_seed"] != second["sampling_seed"] {
		t.Fatalf("sampling_seed should be stable across rounds: %v != %v", first["sampling_seed"], second["sampling_seed"])
	}
	if first["deterministic"] != true {
		t.Fatalf("deterministic should be true when deterministic_level=deterministic: %v", first["deterministic"])
	}
	if first["strong_deterministic"] != false {
		t.Fatalf("strong_deterministic should be false when deterministic_level=deterministic: %v", first["strong_deterministic"])
	}
	if first["deterministic_level"] != "deterministic" {
		t.Fatalf("deterministic_level should be normalized as deterministic: %v", first["deterministic_level"])
	}
}

func TestCompileRoundConfigUsesSeedOverridesWhenProvided(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790ad1"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {
				"global_seed": "seed-fixed",
				"split_seed": 17,
				"train_seed": 27,
				"sampling_seed": 37
			}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	if got := cast.ToInt(config["split_seed"]); got != 17 {
		t.Fatalf("split_seed override mismatch: %d", got)
	}
	if got := cast.ToInt(config["train_seed"]); got != 27 {
		t.Fatalf("train_seed override mismatch: %d", got)
	}
	if got := cast.ToInt(config["sampling_seed"]); got != 37 {
		t.Fatalf("sampling_seed override mismatch: %d", got)
	}
}

func TestCompileRoundConfigAllowsPartialSeedOverrides(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790ad2"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {
				"global_seed": "seed-fixed",
				"split_seed": 17
			}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	if got := cast.ToInt(config["split_seed"]); got != 17 {
		t.Fatalf("split_seed override mismatch: %d", got)
	}
	wantTrain := int(deriveScopedSeed("seed-fixed", "train"))
	if got := cast.ToInt(config["train_seed"]); got != wantTrain {
		t.Fatalf("train_seed should fallback to derived value: got=%d want=%d", got, wantTrain)
	}
	wantSampling := int(deriveScopedSeed("seed-fixed", "sampling"))
	if got := cast.ToInt(config["sampling_seed"]); got != wantSampling {
		t.Fatalf("sampling_seed should fallback to derived value: got=%d want=%d", got, wantSampling)
	}
}

func TestCompileRoundConfigDeterministicLevelDefaultsToOff(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790acb"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {"global_seed": "seed-fixed"}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	if config["deterministic_level"] != "off" {
		t.Fatalf("deterministic_level should default to off: %v", config["deterministic_level"])
	}
	if config["deterministic"] != false {
		t.Fatalf("deterministic should be false when deterministic_level=off: %v", config["deterministic"])
	}
	if config["strong_deterministic"] != false {
		t.Fatalf("strong_deterministic should be false when deterministic_level=off: %v", config["strong_deterministic"])
	}
}

func TestCompileRoundConfigStrongDeterministicLevel(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790acc"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {"global_seed": "seed-fixed", "deterministic_level": "strong_deterministic"}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	if config["deterministic_level"] != "strong_deterministic" {
		t.Fatalf("deterministic_level should be normalized as strong_deterministic: %v", config["deterministic_level"])
	}
	if config["deterministic"] != true {
		t.Fatalf("deterministic should be true when deterministic_level=strong_deterministic: %v", config["deterministic"])
	}
	if config["strong_deterministic"] != true {
		t.Fatalf("strong_deterministic should be true when deterministic_level=strong_deterministic: %v", config["strong_deterministic"])
	}
}

func TestCompileRoundConfigIncludesTrainingLabelFilter(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790acd"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {"global_seed": "seed-fixed"},
			"training": {
				"include_label_ids": ["label-b", "label-a", "label-a", ""],
				"negative_sample_ratio": 1.5
			}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	training, ok := config["training"].(map[string]any)
	if !ok {
		t.Fatalf("training config should be propagated to round config: %T", config["training"])
	}
	got := cast.ToStringSlice(training["include_label_ids"])
	want := []string{"label-a", "label-b"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("training include_label_ids mismatch: got=%v want=%v", got, want)
	}
	if gotRatio := cast.ToFloat64(training["negative_sample_ratio"]); gotRatio != 1.5 {
		t.Fatalf("training negative_sample_ratio mismatch: got=%v want=%v", gotRatio, 1.5)
	}
}

func TestCompileRoundConfigSupportsUnlimitedNegativeSampleRatio(t *testing.T) {
	loop := loopRow{
		ID:             mustUUID("f1fa6112-6ea6-4367-a83a-e6f993790acf"),
		Mode:           modeAL,
		QueryBatchSize: 128,
		ModelArch:      "yolo_det_v1",
		Config: []byte(`{
			"sampling": {"strategy": "random_baseline", "topk": 32},
			"reproducibility": {"global_seed": "seed-fixed"},
			"training": {"negative_sample_ratio": null}
		}`),
	}
	config := compileRoundConfig(loop, 1)
	training, ok := config["training"].(map[string]any)
	if !ok {
		t.Fatalf("training config should be propagated to round config: %T", config["training"])
	}
	if _, exists := training["negative_sample_ratio"]; !exists {
		t.Fatalf("training negative_sample_ratio should be present")
	}
	if training["negative_sample_ratio"] != nil {
		t.Fatalf("training negative_sample_ratio should be nil for unlimited mode: %v", training["negative_sample_ratio"])
	}
}

func TestCompileStepConfigKeepsTrainingOnlyForTrainEval(t *testing.T) {
	roundConfig := map[string]any{
		"sampling": map[string]any{
			"strategy": "random_baseline",
			"topk":     32,
		},
		"training": map[string]any{
			"include_label_ids":     []string{"label-b", "label-a"},
			"negative_sample_ratio": 2,
		},
	}

	trainConfig := compileStepConfig(roundConfig, db.SteptypeTRAIN, modeAL)
	evalConfig := compileStepConfig(roundConfig, db.SteptypeEVAL, modeAL)
	scoreConfig := compileStepConfig(roundConfig, db.SteptypeSCORE, modeAL)

	trainTraining, ok := trainConfig["training"].(map[string]any)
	if !ok {
		t.Fatalf("train step should keep training config: %T", trainConfig["training"])
	}
	evalTraining, ok := evalConfig["training"].(map[string]any)
	if !ok {
		t.Fatalf("eval step should keep training config: %T", evalConfig["training"])
	}
	if _, ok := scoreConfig["training"]; ok {
		t.Fatal("score step should not keep training config")
	}
	want := []string{"label-a", "label-b"}
	if got := cast.ToStringSlice(trainTraining["include_label_ids"]); !reflect.DeepEqual(got, want) {
		t.Fatalf("train include_label_ids mismatch: got=%v want=%v", got, want)
	}
	if got := cast.ToStringSlice(evalTraining["include_label_ids"]); !reflect.DeepEqual(got, want) {
		t.Fatalf("eval include_label_ids mismatch: got=%v want=%v", got, want)
	}
	if got := cast.ToFloat64(trainTraining["negative_sample_ratio"]); got != 2 {
		t.Fatalf("train negative_sample_ratio mismatch: got=%v want=%v", got, 2)
	}
	if got := cast.ToFloat64(evalTraining["negative_sample_ratio"]); got != 2 {
		t.Fatalf("eval negative_sample_ratio mismatch: got=%v want=%v", got, 2)
	}
}

func TestResolveModelArtifactCandidatesKeepsPrimaryThenFallbacks(t *testing.T) {
	requirements := stepRuntimeRequirements{
		requiresTrainedModel:    true,
		primaryModelArtifactKey: "best.pt",
		fallbackArtifactKeys:    []string{"best.pth"},
	}
	got := resolveModelArtifactCandidates(requirements)
	want := []string{"best.pt", "best.pth"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("artifact candidates mismatch: got=%v want=%v", got, want)
	}
}

func TestResolveModelArtifactCandidatesDeduplicatesAndAppliesDefault(t *testing.T) {
	requirements := stepRuntimeRequirements{
		requiresTrainedModel:    true,
		primaryModelArtifactKey: " ",
		fallbackArtifactKeys:    []string{"best.pth", "best.pth", "best.pt"},
	}
	got := resolveModelArtifactCandidates(requirements)
	want := []string{"best.pth", "best.pt"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("artifact candidates dedupe mismatch: got=%v want=%v", got, want)
	}
}

func TestInjectRuntimeArtifactRefsKeepsPluginParamsStable(t *testing.T) {
	trainTaskID := mustUUID("0df5d8f3-a3a3-45ba-bc7d-194a72aaf0b1")
	trainStepID := mustUUID("9d566615-cf74-4d48-8b7c-e2baad1b8c0f")
	injectedAt := time.Date(2026, time.March, 10, 1, 2, 3, 0, time.UTC)

	got := injectRuntimeArtifactRefs(
		map[string]any{
			"plugin": map[string]any{
				"model_source":     "runtime_artifact",
				"model_custom_ref": "should-be-removed",
				"epochs":           20,
			},
			"sampling": map[string]any{
				"topk": 32,
			},
		},
		trainTaskID,
		trainStepID,
		"best.pt",
		injectedAt,
	)

	plugin, ok := got["plugin"].(map[string]any)
	if !ok {
		t.Fatalf("plugin params should remain a map, got=%T", got["plugin"])
	}
	if _, exists := plugin["model_source"]; exists {
		t.Fatalf("plugin params should not expose runtime_artifact model_source: %+v", plugin)
	}
	if _, exists := plugin["model_custom_ref"]; exists {
		t.Fatalf("plugin params should not expose model_custom_ref during dispatch: %+v", plugin)
	}
	if cast.ToInt(plugin["epochs"]) != 20 {
		t.Fatalf("unrelated plugin params should be preserved, got=%+v", plugin)
	}

	refs, ok := got["_runtime_artifact_refs"].(map[string]any)
	if !ok {
		t.Fatalf("_runtime_artifact_refs should be a map, got=%T", got["_runtime_artifact_refs"])
	}
	modelRef, ok := refs["model"].(map[string]any)
	if !ok {
		t.Fatalf("model runtime ref should be a map, got=%T", refs["model"])
	}
	if cast.ToString(modelRef["source_task_id"]) != trainTaskID.String() {
		t.Fatalf("source_task_id mismatch: %v", modelRef["source_task_id"])
	}
	if cast.ToString(modelRef["artifact_name"]) != "best.pt" {
		t.Fatalf("artifact_name mismatch: %v", modelRef["artifact_name"])
	}
	if cast.ToString(modelRef["from_step_id"]) != trainStepID.String() {
		t.Fatalf("from_step_id mismatch: %v", modelRef["from_step_id"])
	}
	if cast.ToString(modelRef["injected_at"]) != injectedAt.Format(time.RFC3339) {
		t.Fatalf("injected_at mismatch: %v", modelRef["injected_at"])
	}
}

func TestShouldApplyRuntimeTaskStatus(t *testing.T) {
	if shouldApplyRuntimeTaskStatus(db.Runtimetaskstatus("")) {
		t.Fatal("empty runtime status should be ignored")
	}
	if shouldApplyRuntimeTaskStatus(db.RuntimetaskstatusPENDING) {
		t.Fatal("runtime PENDING status should be ignored")
	}
	if !shouldApplyRuntimeTaskStatus(db.RuntimetaskstatusRUNNING) {
		t.Fatal("runtime RUNNING status should be applied")
	}
}

func TestCanLoopLifecycleTransitionMatrix(t *testing.T) {
	if !canLoopLifecycleTransition(db.LooplifecyclePAUSED, db.LooplifecycleRUNNING) {
		t.Fatal("PAUSED -> RUNNING should be allowed")
	}
	if !canLoopLifecycleTransition(db.LooplifecycleFAILED, db.LooplifecycleRUNNING) {
		t.Fatal("FAILED -> RUNNING should be allowed for retry_round")
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

func TestTaskStatusCountsForAPINormalizesToLowercase(t *testing.T) {
	counts := map[db.Runtimetaskstatus]int{
		db.RuntimetaskstatusSUCCEEDED:     4,
		db.RuntimetaskstatusRUNNING:       1,
		db.Runtimetaskstatus("succeeded"): 2,
		db.Runtimetaskstatus(" "):         7,
	}
	got := taskStatusCountsForAPI(counts)
	want := map[string]int{
		"succeeded": 6,
		"running":   1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("step status counts normalization mismatch: got=%v want=%v", got, want)
	}
}

func TestSummarizeRoundStateFromTaskStatusTreatsPreRunStagesAsRunning(t *testing.T) {
	state := summarizeRoundStateFromTaskStatus(
		map[db.Runtimetaskstatus]int{
			db.RuntimetaskstatusSYNCINGENV:     1,
			db.RuntimetaskstatusPROBINGRUNTIME: 1,
			db.RuntimetaskstatusBINDINGDEVICE:  1,
		},
		3,
	)
	if state != roundRunning {
		t.Fatalf("pre-run stages should keep round in RUNNING, got=%s", state)
	}
}

func TestExtractPredictionSnapshotFromReasonSnakeCase(t *testing.T) {
	reason := map[string]any{
		"strategy": "uncertainty",
		"prediction_snapshot": map[string]any{
			"label_id":   "0f9cf52f-bbd9-4fca-a6f5-47c3d04de6b2",
			"confidence": 0.91,
		},
	}
	got := extractPredictionSnapshotFromReason(reason)
	want := map[string]any{
		"label_id":   "0f9cf52f-bbd9-4fca-a6f5-47c3d04de6b2",
		"confidence": 0.91,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("prediction snapshot extract mismatch: got=%v want=%v", got, want)
	}
}

func TestExtractPredictionSnapshotFromReasonFallbackAndInvalid(t *testing.T) {
	camel := map[string]any{
		"predictionSnapshot": map[string]any{"pred_count": float64(2)},
	}
	gotCamel := extractPredictionSnapshotFromReason(camel)
	if !reflect.DeepEqual(gotCamel, map[string]any{"pred_count": float64(2)}) {
		t.Fatalf("predictionSnapshot camelCase extract mismatch: got=%v", gotCamel)
	}

	invalid := map[string]any{"prediction_snapshot": "not-object"}
	gotInvalid := extractPredictionSnapshotFromReason(invalid)
	if !reflect.DeepEqual(gotInvalid, map[string]any{}) {
		t.Fatalf("invalid snapshot should fallback to empty object: got=%v", gotInvalid)
	}
}

func TestBuildTaskResultCandidateRows(t *testing.T) {
	reason, err := structpb.NewStruct(map[string]any{
		"prediction_snapshot": map[string]any{
			"base_predictions": []any{
				map[string]any{"class_index": float64(1), "confidence": float64(0.8)},
			},
		},
	})
	if err != nil {
		t.Fatalf("build reason struct failed: %v", err)
	}
	rows := buildTaskResultCandidateRows([]*runtimecontrolv1.QueryCandidate{
		{
			SampleId: "sample-a",
			Score:    0.66,
			Reason:   reason,
		},
	})
	if len(rows) != 1 {
		t.Fatalf("candidate rows size mismatch: %d", len(rows))
	}
	got := rows[0]
	if got["sample_id"] != "sample-a" {
		t.Fatalf("sample_id mismatch: %v", got["sample_id"])
	}
	if got["rank"] != 1 {
		t.Fatalf("rank mismatch: %v", got["rank"])
	}
	if got["score"] != float64(0.66) {
		t.Fatalf("score mismatch: %v", got["score"])
	}
	snapshot, ok := got["prediction_snapshot"].(map[string]any)
	if !ok {
		t.Fatalf("prediction_snapshot type mismatch: %T", got["prediction_snapshot"])
	}
	if _, exists := snapshot["base_predictions"]; !exists {
		t.Fatalf("prediction_snapshot should include base_predictions: %v", snapshot)
	}
}

func TestDependencyRowsReadyRequiresSucceededAndMaterialized(t *testing.T) {
	rows := []db.GetDependencyTaskStatusesByIDsRow{
		{
			Status:        db.RuntimetaskstatusSUCCEEDED,
			ResultReadyAt: pgtype.Timestamptz{Valid: true},
		},
		{
			Status:        db.RuntimetaskstatusSUCCEEDED,
			ResultReadyAt: pgtype.Timestamptz{Valid: true},
		},
	}
	if !dependencyRowsReady(rows, 2) {
		t.Fatal("all succeeded dependencies with materialized results should pass")
	}

	rows[1].ResultReadyAt = pgtype.Timestamptz{Valid: false}
	if dependencyRowsReady(rows, 2) {
		t.Fatal("dependency without result_ready_at should block")
	}

	rows[1] = db.GetDependencyTaskStatusesByIDsRow{
		Status:        db.RuntimetaskstatusRUNNING,
		ResultReadyAt: pgtype.Timestamptz{Valid: true},
	}
	if dependencyRowsReady(rows, 2) {
		t.Fatal("dependency not in succeeded status should block")
	}

	if dependencyRowsReady(rows[:1], 2) {
		t.Fatal("dependency count mismatch should block")
	}
}

func TestIsOrchestratorRetryableErrorIncludesSelectCandidatesNotReady(t *testing.T) {
	wrapped := fmt.Errorf("wrapped: %w", errSelectCandidatesNotReady)
	if !isOrchestratorRetryableError(wrapped) {
		t.Fatal("select candidates not ready error should be retryable")
	}
}
