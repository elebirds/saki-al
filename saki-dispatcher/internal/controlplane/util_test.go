package controlplane

import (
	"testing"

	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func TestDecodeStepEventStatusUsesLowercasePayload(t *testing.T) {
	event := &runtimecontrolv1.StepEvent{
		EventPayload: &runtimecontrolv1.StepEvent_StatusEvent{
			StatusEvent: &runtimecontrolv1.StatusEvent{Status: runtimecontrolv1.RuntimeStepStatus_RUNNING, Reason: "step running"},
		},
	}
	eventType, payload, statusValue := decodeStepEvent(event)
	if eventType != "status" {
		t.Fatalf("unexpected event type: %s", eventType)
	}
	if got := payload["status"]; got != "running" {
		t.Fatalf("status payload should be lowercase, got=%v", got)
	}
	if statusValue != stepRunning {
		t.Fatalf("status value mapping mismatch: %s", statusValue)
	}
}

func TestDecodeStepEventLogPreservesStructuredFields(t *testing.T) {
	messageArgs, err := structpb.NewStruct(map[string]any{"step": float64(3)})
	if err != nil {
		t.Fatalf("build message args struct failed: %v", err)
	}
	meta, err := structpb.NewStruct(map[string]any{
		"source":     "worker_stdio",
		"stream":     "stderr",
		"group_id":   "group-1",
		"line_count": float64(2),
	})
	if err != nil {
		t.Fatalf("build meta struct failed: %v", err)
	}
	event := &runtimecontrolv1.StepEvent{
		EventPayload: &runtimecontrolv1.StepEvent_LogEvent{
			LogEvent: &runtimecontrolv1.LogEvent{
				Level:       "DEBUG",
				Message:     "display",
				RawMessage:  "raw",
				MessageKey:  "runtime.metric.update",
				MessageArgs: messageArgs,
				Meta:        meta,
			},
		},
	}

	eventType, payload, statusValue := decodeStepEvent(event)
	if eventType != "log" {
		t.Fatalf("unexpected event type: %s", eventType)
	}
	if statusValue != "" {
		t.Fatalf("log event should not carry status value: %s", statusValue)
	}
	if payload["raw_message"] != "raw" {
		t.Fatalf("raw_message mismatch: %v", payload["raw_message"])
	}
	if payload["message_key"] != "runtime.metric.update" {
		t.Fatalf("message_key mismatch: %v", payload["message_key"])
	}
	metaPayload, ok := payload["meta"].(map[string]any)
	if !ok {
		t.Fatalf("meta payload type mismatch: %T", payload["meta"])
	}
	if metaPayload["source"] != "worker_stdio" {
		t.Fatalf("meta source mismatch: %v", metaPayload["source"])
	}
	messageArgsPayload, ok := payload["message_args"].(map[string]any)
	if !ok {
		t.Fatalf("message args payload type mismatch: %T", payload["message_args"])
	}
	if messageArgsPayload["step"] != float64(3) {
		t.Fatalf("message args mismatch: %v", messageArgsPayload["step"])
	}
}
