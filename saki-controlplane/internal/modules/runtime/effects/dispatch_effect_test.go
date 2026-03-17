package effects

import (
	"context"
	"testing"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

func TestDispatchEffectAssignTaskTopicInvokesControlClient(t *testing.T) {
	client := &fakeDispatchClient{}
	effect := NewDispatchEffect(client)

	err := effect.Apply(context.Background(), commands.OutboxEvent{
		Topic:       commands.AssignTaskOutboxTopic,
		AggregateID: "550e8400-e29b-41d4-a716-446655440000",
		Payload:     []byte(`{"task_id":"550e8400-e29b-41d4-a716-446655440000","execution_id":"exec-1","agent_id":"agent-1","task_kind":"PREDICTION","task_type":"predict","attempt":1,"max_attempts":3,"resolved_params":{"prompt":"hello"},"depends_on_task_ids":[],"leader_epoch":7}`),
	})
	if err != nil {
		t.Fatalf("apply dispatch effect: %v", err)
	}

	if client.last == nil || client.last.TaskId != "550e8400-e29b-41d4-a716-446655440000" {
		t.Fatalf("unexpected assign request: %+v", client.last)
	}
	if client.last.ExecutionId != "exec-1" || client.last.TaskType != "predict" {
		t.Fatalf("unexpected assign request: %+v", client.last)
	}
	if string(client.last.Payload) != `{"prompt":"hello"}` {
		t.Fatalf("unexpected assign payload: %s", string(client.last.Payload))
	}
}

type fakeDispatchClient struct {
	last *runtimev1.AssignTaskRequest
}

func (f *fakeDispatchClient) AssignTask(_ context.Context, req *runtimev1.AssignTaskRequest) error {
	f.last = req
	return nil
}
