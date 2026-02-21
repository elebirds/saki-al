package runtimeclient

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-agent/internal/agent"
	runtimecontrolv1 "github.com/elebirds/saki/saki-agent/internal/gen/runtimecontrolv1"
)

func TestHandleAssignRejectWhenDraining(t *testing.T) {
	daemon, err := agent.NewWithLogger(agent.Config{}, zerolog.Nop())
	if err != nil {
		t.Fatalf("create agent failed: %v", err)
	}
	daemon.SetDraining(true)

	client := New(Config{Target: "127.0.0.1:50051"}, daemon, zerolog.Nop())
	messages, _ := client.handleIncoming(context.Background(), &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignStep{
			AssignStep: &runtimecontrolv1.AssignStep{
				RequestId: "req-draining",
				Step:      &runtimecontrolv1.StepPayload{StepId: "step-1"},
			},
		},
	})
	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}
	ack := messages[0].GetAck()
	if ack == nil {
		t.Fatalf("expected ack response")
	}
	if ack.GetStatus() != runtimecontrolv1.AckStatus_ERROR {
		t.Fatalf("unexpected ack status: %s", ack.GetStatus().String())
	}
	if ack.GetReason() != runtimecontrolv1.AckReason_ACK_REASON_STOPPING {
		t.Fatalf("unexpected ack reason: %s", ack.GetReason().String())
	}
}

func TestAssignBusyAndStopLifecycle(t *testing.T) {
	daemon, err := agent.NewWithLogger(agent.Config{}, zerolog.Nop())
	if err != nil {
		t.Fatalf("create agent failed: %v", err)
	}
	client := New(Config{Target: "127.0.0.1:50051"}, daemon, zerolog.Nop())
	defer client.abortRunningStep()

	assignMessages, _ := client.handleIncoming(context.Background(), &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignStep{
			AssignStep: &runtimecontrolv1.AssignStep{
				RequestId: "req-1",
				Step: &runtimecontrolv1.StepPayload{
					StepId: "step-1",
					EnvOverrides: map[string]string{
						"SAKI_AGENT_STUB_DURATION_SEC": "5",
					},
				},
			},
		},
	})
	if len(assignMessages) != 2 {
		t.Fatalf("expected 2 assign responses, got %d", len(assignMessages))
	}
	assignAck := assignMessages[0].GetAck()
	if assignAck == nil || assignAck.GetStatus() != runtimecontrolv1.AckStatus_OK {
		t.Fatalf("expected assign ack ok, got %+v", assignAck)
	}
	runningEvent := assignMessages[1].GetStepEvent()
	if runningEvent == nil || runningEvent.GetStatusEvent().GetStatus() != runtimecontrolv1.RuntimeStepStatus_RUNNING {
		t.Fatalf("expected running step event, got %+v", runningEvent)
	}

	heartbeat := client.buildHeartbeatMessage(nil, time.Now().Add(-time.Second)).GetHeartbeat()
	if heartbeat == nil {
		t.Fatal("expected heartbeat message")
	}
	if !heartbeat.GetBusy() || heartbeat.GetCurrentStepId() != "step-1" {
		t.Fatalf("unexpected heartbeat busy/current_step_id: busy=%t step=%s", heartbeat.GetBusy(), heartbeat.GetCurrentStepId())
	}

	busyMessages, _ := client.handleIncoming(context.Background(), &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignStep{
			AssignStep: &runtimecontrolv1.AssignStep{
				RequestId: "req-2",
				Step:      &runtimecontrolv1.StepPayload{StepId: "step-2"},
			},
		},
	})
	if len(busyMessages) != 1 {
		t.Fatalf("expected 1 busy response, got %d", len(busyMessages))
	}
	busyAck := busyMessages[0].GetAck()
	if busyAck == nil || busyAck.GetReason() != runtimecontrolv1.AckReason_ACK_REASON_EXECUTOR_BUSY {
		t.Fatalf("expected executor busy ack, got %+v", busyAck)
	}

	stopMessages, _ := client.handleIncoming(context.Background(), &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_StopStep{
			StopStep: &runtimecontrolv1.StopStep{
				RequestId: "stop-1",
				StepId:    "step-1",
				Reason:    "manual stop",
			},
		},
	})
	if len(stopMessages) != 1 {
		t.Fatalf("expected 1 stop response, got %d", len(stopMessages))
	}
	stopAck := stopMessages[0].GetAck()
	if stopAck == nil || stopAck.GetReason() != runtimecontrolv1.AckReason_ACK_REASON_STOPPING {
		t.Fatalf("expected stop ack stopping, got %+v", stopAck)
	}

	cancelledEvent, cancelledResult := waitForTerminalMessages(t, client.outgoingCh, 2*time.Second)
	if cancelledEvent.GetStatusEvent().GetStatus() != runtimecontrolv1.RuntimeStepStatus_CANCELLED {
		t.Fatalf("expected cancelled event, got %s", cancelledEvent.GetStatusEvent().GetStatus().String())
	}
	if cancelledResult.GetStatus() != runtimecontrolv1.RuntimeStepStatus_CANCELLED {
		t.Fatalf("expected cancelled result, got %s", cancelledResult.GetStatus().String())
	}
}

func TestAssignTerminalFailureWhenNoStop(t *testing.T) {
	daemon, err := agent.NewWithLogger(agent.Config{}, zerolog.Nop())
	if err != nil {
		t.Fatalf("create agent failed: %v", err)
	}
	client := New(Config{Target: "127.0.0.1:50051"}, daemon, zerolog.Nop())
	defer client.abortRunningStep()

	assignMessages, _ := client.handleIncoming(context.Background(), &runtimecontrolv1.RuntimeMessage{
		Payload: &runtimecontrolv1.RuntimeMessage_AssignStep{
			AssignStep: &runtimecontrolv1.AssignStep{
				RequestId: "req-auto-fail",
				Step: &runtimecontrolv1.StepPayload{
					StepId: "step-fail",
					EnvOverrides: map[string]string{
						"SAKI_AGENT_STUB_DURATION_SEC": "0.05",
					},
				},
			},
		},
	})
	if len(assignMessages) != 2 {
		t.Fatalf("expected 2 assign responses, got %d", len(assignMessages))
	}

	failedEvent, failedResult := waitForTerminalMessages(t, client.outgoingCh, 2*time.Second)
	if failedEvent.GetStatusEvent().GetStatus() != runtimecontrolv1.RuntimeStepStatus_FAILED {
		t.Fatalf("expected failed event, got %s", failedEvent.GetStatusEvent().GetStatus().String())
	}
	if failedResult.GetStatus() != runtimecontrolv1.RuntimeStepStatus_FAILED {
		t.Fatalf("expected failed result, got %s", failedResult.GetStatus().String())
	}
	if !strings.Contains(failedResult.GetErrorMessage(), "尚未接入") {
		t.Fatalf("unexpected failed result message: %s", failedResult.GetErrorMessage())
	}
}

func TestBuildRegisterMessageLoadsPluginsFromKernelYAML(t *testing.T) {
	root := t.TempDir()
	kernelDir := filepath.Join(root, "example")
	if err := os.MkdirAll(kernelDir, 0o755); err != nil {
		t.Fatalf("mkdir kernel dir failed: %v", err)
	}
	manifest := `id: "example-train"
version: "0.2.0"
display_name: "Example Train"
supported_step_types:
  - "TRAIN"
supported_strategies:
  - "entropy"
`
	if err := os.WriteFile(filepath.Join(kernelDir, "kernel.yaml"), []byte(manifest), 0o644); err != nil {
		t.Fatalf("write kernel manifest failed: %v", err)
	}

	client := New(Config{
		Target:     "127.0.0.1:50051",
		KernelsDir: root,
	}, nil, zerolog.Nop())
	message, _, err := client.buildRegisterMessage()
	if err != nil {
		t.Fatalf("buildRegisterMessage failed: %v", err)
	}
	register := message.GetRegister()
	if register == nil {
		t.Fatal("expected register payload")
	}
	if len(register.GetPlugins()) != 1 {
		t.Fatalf("expected 1 plugin, got %d", len(register.GetPlugins()))
	}
	plugin := register.GetPlugins()[0]
	if plugin.GetPluginId() != "example-train" {
		t.Fatalf("unexpected plugin id: %s", plugin.GetPluginId())
	}
	if plugin.GetVersion() != "0.2.0" {
		t.Fatalf("unexpected plugin version: %s", plugin.GetVersion())
	}
}

func TestPluginCatalogCachedInMemoryAfterFirstLoad(t *testing.T) {
	root := t.TempDir()
	kernelDir := filepath.Join(root, "example")
	if err := os.MkdirAll(kernelDir, 0o755); err != nil {
		t.Fatalf("mkdir kernel dir failed: %v", err)
	}
	manifestPath := filepath.Join(kernelDir, "kernel.yaml")
	manifest := `id: "cached-plugin"
version: "1.0.0"
display_name: "Cached Plugin"
supported_step_types:
  - "TRAIN"
`
	if err := os.WriteFile(manifestPath, []byte(manifest), 0o644); err != nil {
		t.Fatalf("write kernel manifest failed: %v", err)
	}

	client := New(Config{
		Target:     "127.0.0.1:50051",
		KernelsDir: root,
	}, nil, zerolog.Nop())

	first, _, err := client.buildRegisterMessage()
	if err != nil {
		t.Fatalf("first buildRegisterMessage failed: %v", err)
	}
	if len(first.GetRegister().GetPlugins()) != 1 {
		t.Fatalf("expected 1 plugin on first load, got %d", len(first.GetRegister().GetPlugins()))
	}

	if err := os.Remove(manifestPath); err != nil {
		t.Fatalf("remove kernel manifest failed: %v", err)
	}
	second, _, err := client.buildRegisterMessage()
	if err != nil {
		t.Fatalf("second buildRegisterMessage failed: %v", err)
	}
	if len(second.GetRegister().GetPlugins()) != 1 {
		t.Fatalf("expected cached plugin after source removal, got %d", len(second.GetRegister().GetPlugins()))
	}
	if second.GetRegister().GetPlugins()[0].GetPluginId() != "cached-plugin" {
		t.Fatalf("unexpected cached plugin id: %s", second.GetRegister().GetPlugins()[0].GetPluginId())
	}

	status := client.Status()
	if !status.PluginCatalogLoaded {
		t.Fatalf("expected plugin catalog loaded in status")
	}
	if status.PluginCatalogSize != 1 {
		t.Fatalf("expected plugin catalog size 1, got %d", status.PluginCatalogSize)
	}
	if status.PluginCatalogAt.IsZero() {
		t.Fatalf("expected plugin catalog loaded_at set")
	}
	if status.PluginCatalogError != "" {
		t.Fatalf("unexpected plugin catalog error: %s", status.PluginCatalogError)
	}
}

func TestPluginCatalogStatusContainsLoadError(t *testing.T) {
	missingDir := filepath.Join(t.TempDir(), "missing")
	client := New(Config{
		Target:     "127.0.0.1:50051",
		KernelsDir: missingDir,
	}, nil, zerolog.Nop())

	message, _, err := client.buildRegisterMessage()
	if err != nil {
		t.Fatalf("buildRegisterMessage failed: %v", err)
	}
	register := message.GetRegister()
	if register == nil {
		t.Fatalf("expected register payload")
	}
	if len(register.GetPlugins()) != 0 {
		t.Fatalf("expected no plugins, got %d", len(register.GetPlugins()))
	}

	status := client.Status()
	if !status.PluginCatalogLoaded {
		t.Fatalf("expected plugin catalog loaded state")
	}
	if status.PluginCatalogError == "" {
		t.Fatalf("expected plugin catalog load error")
	}
	if status.PluginCatalogSize != 0 {
		t.Fatalf("expected plugin catalog size 0, got %d", status.PluginCatalogSize)
	}
}

func waitForTerminalMessages(
	t *testing.T,
	queue <-chan *runtimecontrolv1.RuntimeMessage,
	timeout time.Duration,
) (*runtimecontrolv1.StepEvent, *runtimecontrolv1.StepResult) {
	t.Helper()

	var event *runtimecontrolv1.StepEvent
	var result *runtimecontrolv1.StepResult
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	for event == nil || result == nil {
		select {
		case message := <-queue:
			if message == nil {
				continue
			}
			if stepEvent := message.GetStepEvent(); stepEvent != nil {
				event = stepEvent
			}
			if stepResult := message.GetStepResult(); stepResult != nil {
				result = stepResult
			}
		case <-timer.C:
			t.Fatalf("timeout waiting terminal messages: event=%v result=%v", event != nil, result != nil)
		}
	}
	return event, result
}
