package connect_test

import (
	"testing"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

func TestRuntimeProtoContractSmoke(t *testing.T) {
	t.Helper()

	var _ = runtimev1connect.NewAgentIngressClient
	var _ = runtimev1connect.NewAgentControlHandler
	_ = runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING
}
