package internalrpc

import (
	"testing"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"google.golang.org/protobuf/proto"
)

func TestRegisterRequestCodec(t *testing.T) {
	original := &runtimev1.RegisterRequest{
		ExecutorId:   "executor-a",
		Version:      "1.0.0",
		Capabilities: []string{"gpu", "yolo"},
	}

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal register request: %v", err)
	}

	var decoded runtimev1.RegisterRequest
	if err := proto.Unmarshal(wire, &decoded); err != nil {
		t.Fatalf("unmarshal register request: %v", err)
	}

	if decoded.ExecutorId != "executor-a" || len(decoded.Capabilities) != 2 {
		t.Fatalf(
			"unexpected decoded register request executor_id=%q capabilities=%d",
			decoded.ExecutorId,
			len(decoded.Capabilities),
		)
	}
}

func TestHeartbeatRequestCodec(t *testing.T) {
	original := &runtimev1.HeartbeatRequest{
		ExecutorId:     "executor-a",
		AgentVersion:   "1.0.1",
		RunningTaskIds: []string{"task-1", "task-2"},
		SentAtUnixMs:   123456789,
	}

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal heartbeat request: %v", err)
	}

	var decoded runtimev1.HeartbeatRequest
	if err := proto.Unmarshal(wire, &decoded); err != nil {
		t.Fatalf("unmarshal heartbeat request: %v", err)
	}

	if decoded.ExecutorId != "executor-a" || decoded.SentAtUnixMs != 123456789 {
		t.Fatalf(
			"unexpected decoded heartbeat request executor_id=%q sent_at_unix_ms=%d",
			decoded.ExecutorId,
			decoded.SentAtUnixMs,
		)
	}
}

func TestTaskEventEnvelopeCodec(t *testing.T) {
	original := &runtimev1.TaskEventEnvelope{
		ExecutorId:  "executor-a",
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING,
		Payload: &runtimev1.TaskEventEnvelope_Log{
			Log: &runtimev1.TaskLogEvent{
				Level:   "INFO",
				Message: "task started",
			},
		},
	}

	wire, err := proto.Marshal(original)
	if err != nil {
		t.Fatalf("marshal task event envelope: %v", err)
	}

	var decoded runtimev1.TaskEventEnvelope
	if err := proto.Unmarshal(wire, &decoded); err != nil {
		t.Fatalf("unmarshal task event envelope: %v", err)
	}

	logPayload := decoded.GetLog()
	if logPayload == nil || logPayload.Message != "task started" {
		t.Fatalf(
			"unexpected decoded task event envelope phase=%s log=%v",
			decoded.Phase.String(),
			logPayload,
		)
	}
}
