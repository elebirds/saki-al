package runtimeclient

import (
	"context"
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
