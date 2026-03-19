package reporting

import (
	"context"
	"testing"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

func TestRuntimeSinkMapsProgressWorkerEventToTaskEventEnvelope(t *testing.T) {
	pusher := &fakeTaskEventPusher{}
	sink := NewRuntimeSink(pusher, "agent-a", "task-1", "exec-1")

	if err := sink.ReportWorkerEvent(context.Background(), &workerv1.WorkerEvent{
		RequestId: "exec-1",
		TaskId:    "task-1",
		EventType: "progress",
		Payload:   []byte(`{"percent":42,"message":"halfway"}`),
	}); err != nil {
		t.Fatalf("report worker event: %v", err)
	}

	if pusher.last == nil {
		t.Fatal("expected runtime task event envelope")
	}
	if pusher.last.GetAgentId() != "agent-a" || pusher.last.GetTaskId() != "task-1" || pusher.last.GetExecutionId() != "exec-1" {
		t.Fatalf("unexpected envelope identity: %+v", pusher.last)
	}
	progress := pusher.last.GetProgress()
	if progress == nil || progress.GetPercent() != 42 || progress.GetMessage() != "halfway" {
		t.Fatalf("unexpected progress payload: %+v", progress)
	}
}

func TestRuntimeSinkIgnoresMalformedPayload(t *testing.T) {
	pusher := &fakeTaskEventPusher{}
	sink := NewRuntimeSink(pusher, "agent-a", "task-1", "exec-1")

	if err := sink.ReportWorkerEvent(context.Background(), &workerv1.WorkerEvent{
		RequestId: "exec-1",
		TaskId:    "task-1",
		EventType: "progress",
		Payload:   []byte(`{"percent":"oops"}`),
	}); err != nil {
		t.Fatalf("malformed payload should be ignored, got %v", err)
	}

	if pusher.last != nil {
		t.Fatalf("expected malformed payload to be ignored, got %+v", pusher.last)
	}
}

type fakeTaskEventPusher struct {
	last *runtimev1.TaskEventEnvelope
}

func (f *fakeTaskEventPusher) PushTaskEvent(_ context.Context, envelope *runtimev1.TaskEventEnvelope) error {
	f.last = envelope
	return nil
}
