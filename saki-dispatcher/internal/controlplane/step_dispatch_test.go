package controlplane

import (
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func registerExecutorForTest(t *testing.T, dispatcher *dispatch.Dispatcher, executorID string, pluginIDs ...string) {
	t.Helper()
	plugins := make([]*runtimecontrolv1.PluginCapability, 0, len(pluginIDs))
	for _, pluginID := range pluginIDs {
		plugins = append(plugins, &runtimecontrolv1.PluginCapability{PluginId: pluginID})
	}
	_, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		RequestId:  "req-" + executorID,
		ExecutorId: executorID,
		Plugins:    plugins,
	})
	if err != nil {
		t.Fatalf("register executor failed: %v", err)
	}
}

func TestPreferredExecutorIDFromResolvedParams(t *testing.T) {
	params, err := structpb.NewStruct(map[string]any{
		"execution": map[string]any{
			"preferred_executor_id": "executor-a",
		},
	})
	if err != nil {
		t.Fatalf("build params failed: %v", err)
	}
	if got := preferredExecutorIDFromResolvedParams(params); got != "executor-a" {
		t.Fatalf("preferred executor parse mismatch: got=%q", got)
	}

	camelParams, err := structpb.NewStruct(map[string]any{
		"execution": map[string]any{
			"preferredExecutorId": "executor-b",
		},
	})
	if err != nil {
		t.Fatalf("build camel params failed: %v", err)
	}
	if got := preferredExecutorIDFromResolvedParams(camelParams); got != "executor-b" {
		t.Fatalf("camel preferred executor parse mismatch: got=%q", got)
	}
}

func TestPickExecutorForStepDispatchWithLoopPreferredExecutorAvailable(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "demo_det_v1")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")

	service := &Service{dispatcher: dispatcher}
	executorID, deferredByAffinity, blockedByLoopBinding := service.pickExecutorForStepDispatch(
		"demo_det_v1",
		nil,
		"",
		"executor-a",
		nil,
	)
	if blockedByLoopBinding {
		t.Fatal("preferred executor should not be blocked when available")
	}
	if deferredByAffinity {
		t.Fatal("strict preferred dispatch should not be deferred by affinity")
	}
	if executorID != "executor-a" {
		t.Fatalf("preferred executor dispatch mismatch: got=%q", executorID)
	}
}

func TestPickExecutorForStepDispatchWithLoopPreferredExecutorUnavailableFallsBack(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "demo_det_v1")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")
	dispatcher.UnregisterExecutor("executor-a")

	service := &Service{dispatcher: dispatcher}
	executorID, deferredByAffinity, blockedByLoopBinding := service.pickExecutorForStepDispatch(
		"demo_det_v1",
		nil,
		"",
		"executor-a",
		nil,
	)
	if deferredByAffinity {
		t.Fatal("preferred executor should fallback immediately when wait window is 0")
	}
	if blockedByLoopBinding {
		t.Fatal("loop preferred executor is now a soft hint, should not hard block")
	}
	if executorID != "executor-b" {
		t.Fatalf("soft preferred dispatch should fallback to available executor, got=%q", executorID)
	}
}

func TestPickExecutorForStepDispatchWithLoopPreferredExecutorUnsupportedPluginFallsBack(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "other_plugin")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")

	service := &Service{dispatcher: dispatcher}
	executorID, deferredByAffinity, blockedByLoopBinding := service.pickExecutorForStepDispatch(
		"demo_det_v1",
		nil,
		"",
		"executor-a",
		nil,
	)
	if deferredByAffinity {
		t.Fatal("preferred executor should fallback immediately when wait window is 0")
	}
	if blockedByLoopBinding {
		t.Fatal("loop preferred executor is now a soft hint, should not hard block")
	}
	if executorID != "executor-b" {
		t.Fatalf("soft preferred dispatch should fallback to available executor, got=%q", executorID)
	}
}

func TestPickExecutorForStepDispatchKeepsRoundAffinityWhenNoLoopPreferred(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "demo_det_v1")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")
	dispatcher.UnregisterExecutor("executor-a")

	service := &Service{
		dispatcher:        dispatcher,
		roundAffinityWait: 2 * time.Second,
	}
	readyAt := time.Now().UTC()
	executorID, deferredByAffinity, blockedByLoopBinding := service.pickExecutorForStepDispatch(
		"demo_det_v1",
		&readyAt,
		"executor-a",
		"",
		nil,
	)
	if blockedByLoopBinding {
		t.Fatal("no loop preferred executor should not trigger strict binding block")
	}
	if !deferredByAffinity {
		t.Fatal("round affinity should defer fallback when preferred dependency executor just became unavailable")
	}
	if executorID != "" {
		t.Fatalf("deferred round affinity should not pick fallback executor, got=%q", executorID)
	}
}

func TestPickExecutorForStepDispatchSkipsReservedExecutors(t *testing.T) {
	dispatcher := dispatch.NewDispatcher()
	registerExecutorForTest(t, dispatcher, "executor-a", "demo_det_v1")
	registerExecutorForTest(t, dispatcher, "executor-b", "demo_det_v1")

	service := &Service{dispatcher: dispatcher}
	reserved := map[string]struct{}{
		"executor-a": {},
	}
	executorID, deferredByAffinity, blockedByLoopBinding := service.pickExecutorForStepDispatch(
		"demo_det_v1",
		nil,
		"",
		"",
		reserved,
	)
	if deferredByAffinity {
		t.Fatal("reserved executor fallback should not defer by affinity")
	}
	if blockedByLoopBinding {
		t.Fatal("reserved executor should not trigger loop binding block")
	}
	if executorID != "executor-b" {
		t.Fatalf("expected non-reserved executor-b, got=%q", executorID)
	}
}
