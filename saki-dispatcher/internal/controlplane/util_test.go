package controlplane

import (
	"testing"

	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
)

func TestDecodeTaskEventStatusUsesLowercasePayload(t *testing.T) {
	event := &runtimecontrolv1.TaskEvent{
		EventPayload: &runtimecontrolv1.TaskEvent_StatusEvent{
			StatusEvent: &runtimecontrolv1.StatusEvent{Status: runtimecontrolv1.RuntimeTaskStatus_RUNNING, Reason: "step running"},
		},
	}
	eventType, payload, statusValue := decodeTaskEvent(event)
	if eventType != "status" {
		t.Fatalf("unexpected event type: %s", eventType)
	}
	if got := payload["status"]; got != "running" {
		t.Fatalf("status payload should be lowercase, got=%v", got)
	}
	if statusValue != taskRunning {
		t.Fatalf("status value mapping mismatch: %s", statusValue)
	}
}

func TestDecodeTaskEventStatusMapsPreRunStages(t *testing.T) {
	event := &runtimecontrolv1.TaskEvent{
		EventPayload: &runtimecontrolv1.TaskEvent_StatusEvent{
			StatusEvent: &runtimecontrolv1.StatusEvent{
				Status: runtimecontrolv1.RuntimeTaskStatus_PROBING_RUNTIME,
				Reason: "runtime probe",
			},
		},
	}
	eventType, payload, statusValue := decodeTaskEvent(event)
	if eventType != "status" {
		t.Fatalf("unexpected event type: %s", eventType)
	}
	if got := payload["status"]; got != "probing_runtime" {
		t.Fatalf("status payload should be lowercase, got=%v", got)
	}
	if statusValue != taskProbingRt {
		t.Fatalf("status value mapping mismatch: %s", statusValue)
	}
}

func TestDecodeTaskEventLogPreservesStructuredFields(t *testing.T) {
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
	event := &runtimecontrolv1.TaskEvent{
		EventPayload: &runtimecontrolv1.TaskEvent_LogEvent{
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

	eventType, payload, statusValue := decodeTaskEvent(event)
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

func TestExtractOracleCommitID(t *testing.T) {
	rawConfig := []byte(`{"mode":{"oracle_commit_id":"4af4e930-4bc0-45fb-b6e8-6f5ec7f9c35a"}}`)
	got := extractOracleCommitID(rawConfig)
	if got != "4af4e930-4bc0-45fb-b6e8-6f5ec7f9c35a" {
		t.Fatalf("oracle commit extraction mismatch: %s", got)
	}
}

func TestExtractOracleCommitIDMissingReturnsEmpty(t *testing.T) {
	if got := extractOracleCommitID([]byte(`{"mode":{}}`)); got != "" {
		t.Fatalf("expected empty oracle commit id, got=%s", got)
	}
	if got := extractOracleCommitID([]byte(`{}`)); got != "" {
		t.Fatalf("expected empty oracle commit id, got=%s", got)
	}
}

func TestExtractSimulationFinalizeTrainDefaultsTrue(t *testing.T) {
	if got := extractSimulationFinalizeTrain([]byte(`{}`)); !got {
		t.Fatalf("expected default finalize_train=true, got=%v", got)
	}
	if got := extractSimulationFinalizeTrain([]byte(`{"mode":{}}`)); !got {
		t.Fatalf("expected missing finalize_train to default true, got=%v", got)
	}
	if got := extractSimulationFinalizeTrain([]byte(`{"mode":{"finalize_train":"invalid"}}`)); !got {
		t.Fatalf("expected invalid finalize_train to default true, got=%v", got)
	}
}

func TestExtractSimulationFinalizeTrainParsesConfiguredValue(t *testing.T) {
	if got := extractSimulationFinalizeTrain([]byte(`{"mode":{"finalize_train":false}}`)); got {
		t.Fatalf("expected finalize_train=false, got=%v", got)
	}
	if got := extractSimulationFinalizeTrain([]byte(`{"mode":{"finalize_train":"true"}}`)); !got {
		t.Fatalf("expected finalize_train=true, got=%v", got)
	}
}
