package protocol

import (
	"testing"

	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
	"google.golang.org/protobuf/proto"
)

func TestWorkerProtoRoundTrip(t *testing.T) {
	messages := []proto.Message{
		&workerv1.ExecuteRequest{
			RequestId: "req-1",
			TaskId:    "task-1",
			Action:    "train",
			Payload:   []byte(`{"epochs":1}`),
		},
		&workerv1.WorkerEvent{
			RequestId: "req-1",
			TaskId:    "task-1",
			EventType: "progress",
			Payload:   []byte(`{"percent":42}`),
		},
		&workerv1.ExecuteResult{
			RequestId: "req-1",
			Ok:        true,
			Payload:   []byte(`{"artifact":"best.pt"}`),
		},
	}

	for _, message := range messages {
		wire, err := proto.Marshal(message)
		if err != nil {
			t.Fatalf("marshal %T: %v", message, err)
		}
		clone := proto.Clone(message)
		proto.Reset(clone)
		if err := proto.Unmarshal(wire, clone); err != nil {
			t.Fatalf("unmarshal %T: %v", message, err)
		}
		if !proto.Equal(message, clone) {
			t.Fatalf("unexpected roundtrip %T", message)
		}
	}
}
