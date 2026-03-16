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

func (e *DispatchEffect) Apply(ctx context.Context, event commands.OutboxEvent) error {
	if event.Topic != "runtime.task.assigned" {
		return nil
	}

	var payload struct {
		TaskID      string `json:"task_id"`
		ExecutionID string `json:"execution_id"`
		TaskType    string `json:"task_type"`
		Payload     []byte `json:"payload"`
	}
	if err := json.Unmarshal(event.Payload, &payload); err != nil {
		return err
	}

	return e.client.AssignTask(ctx, &runtimev1.AssignTaskRequest{
		TaskId:      payload.TaskID,
		ExecutionId: payload.ExecutionID,
		TaskType:    payload.TaskType,
		Payload:     payload.Payload,
	})
}
