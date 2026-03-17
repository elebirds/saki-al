package effects

import (
	"context"
	"encoding/json"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type DispatchClient interface {
	AssignTask(ctx context.Context, req *runtimev1.AssignTaskRequest) error
}

type DispatchEffect struct {
	client DispatchClient
}

func NewDispatchEffect(client DispatchClient) *DispatchEffect {
	return &DispatchEffect{client: client}
}

func (*DispatchEffect) Topic() string {
	return commands.AssignTaskOutboxTopic
}

func (e *DispatchEffect) Apply(ctx context.Context, event commands.OutboxEvent) error {
	if event.Topic != commands.AssignTaskOutboxTopic {
		return nil
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(event.Payload, &payload); err != nil {
		return err
	}

	return e.client.AssignTask(ctx, &runtimev1.AssignTaskRequest{
		TaskId:      payload.TaskID.String(),
		ExecutionId: payload.ExecutionID,
		TaskType:    payload.TaskType,
		Payload:     resolvedParamsPayload(payload.ResolvedParams),
	})
}

func resolvedParamsPayload(raw json.RawMessage) []byte {
	if len(raw) == 0 {
		return []byte(`{}`)
	}
	return append([]byte(nil), raw...)
}
