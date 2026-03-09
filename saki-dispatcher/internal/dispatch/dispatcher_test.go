package dispatch

import (
	"testing"
	"time"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func TestPickExecutorPrefersLeastRecentlyAssigned(t *testing.T) {
	dispatcher := NewDispatcher()
	_, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		RequestId:  "req-a",
		ExecutorId: "executor-a",
		Plugins: []*runtimecontrolv1.PluginCapability{
			{PluginId: "demo_det_v1"},
		},
	})
	if err != nil {
		t.Fatalf("register executor-a failed: %v", err)
	}
	_, err = dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		RequestId:  "req-b",
		ExecutorId: "executor-b",
		Plugins: []*runtimecontrolv1.PluginCapability{
			{PluginId: "demo_det_v1"},
		},
	})
	if err != nil {
		t.Fatalf("register executor-b failed: %v", err)
	}

	dispatcher.mu.Lock()
	dispatcher.sessions["executor-a"].LastAssignedAt = time.Now().UTC()
	dispatcher.sessions["executor-b"].LastAssignedAt = time.Now().UTC().Add(-1 * time.Hour)
	dispatcher.mu.Unlock()

	executorID, ok := dispatcher.PickExecutor("demo_det_v1")
	if !ok {
		t.Fatal("expected an available executor")
	}
	if executorID != "executor-b" {
		t.Fatalf("expected least recently assigned executor-b, got=%q", executorID)
	}
}
