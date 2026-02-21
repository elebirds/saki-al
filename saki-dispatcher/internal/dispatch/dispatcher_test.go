package dispatch

import (
	"testing"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestPickExecutorForStepWithCapabilityRequirements(t *testing.T) {
	yesFlags, _ := structpb.NewStruct(map[string]any{"supports_mps_loss_cpu_fallback": true})
	noFlags, _ := structpb.NewStruct(map[string]any{"supports_mps_loss_cpu_fallback": false})

	dispatcher := NewDispatcher()
	if _, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		ExecutorId:        "node-a",
		Plugins:           []*runtimecontrolv1.PluginCapability{{PluginId: "yolo"}},
		KernelCompatFlags: yesFlags,
	}); err != nil {
		t.Fatalf("register node-a failed: %v", err)
	}
	if _, err := dispatcher.RegisterExecutor(&runtimecontrolv1.Register{
		ExecutorId:        "node-b",
		Plugins:           []*runtimecontrolv1.PluginCapability{{PluginId: "yolo"}},
		KernelCompatFlags: noFlags,
	}); err != nil {
		t.Fatalf("register node-b failed: %v", err)
	}

	picked, ok := dispatcher.PickExecutorForStep("yolo", true)
	if !ok {
		t.Fatal("expected available executor for fallback requirement")
	}
	if picked != "node-a" {
		t.Fatalf("expected node-a, got %s", picked)
	}
}
