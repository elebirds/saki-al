package effects

import (
	"context"
	"encoding/json"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type StopClient interface {
	StopTask(ctx context.Context, req *runtimev1.StopTaskRequest) error
}

type StopEffect struct {
	client StopClient
}

func NewStopEffect(client StopClient) *StopEffect {
	return &StopEffect{client: client}
}

func (*StopEffect) Topic() string {
	return commands.StopTaskOutboxTopic
}

func (e *StopEffect) Apply(ctx context.Context, event commands.OutboxEvent) error {
	if event.Topic != commands.StopTaskOutboxTopic {
		return nil
	}

	var payload commands.StopTaskOutboxPayload
	if err := json.Unmarshal(event.Payload, &payload); err != nil {
		return err
	}

	return e.client.StopTask(ctx, &runtimev1.StopTaskRequest{
		TaskId:      payload.TaskID.String(),
		ExecutionId: payload.ExecutionID,
		Reason:      payload.Reason,
	})
}
