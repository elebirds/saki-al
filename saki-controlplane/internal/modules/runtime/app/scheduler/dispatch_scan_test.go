package scheduler

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

func TestDispatchScanClaimsPendingTaskAndAppendsAssignOutbox(t *testing.T) {
	taskID := uuid.New()
	store := &fakeDispatchTaskStore{
		assignedTask: &commands.ClaimedTask{
			ID:                 taskID,
			TaskKind:           "PREDICTION",
			TaskType:           "predict",
			CurrentExecutionID: "exec-dispatch-1",
			AssignedAgentID:    "agent-dispatch-1",
			Attempt:            1,
			MaxAttempts:        1,
			ResolvedParams:     []byte(`{}`),
			DependsOnTaskIDs:   nil,
			LeaderEpoch:        11,
		},
	}
	handler := commands.NewAssignTaskHandler(store)
	scan := NewDispatchScan(handler, "agent-dispatch-1")

	if err := scan.Dispatch(context.Background(), DispatchCommand{LeaderEpoch: 11}); err != nil {
		t.Fatalf("dispatch scan: %v", err)
	}

	if store.calledWith == nil {
		t.Fatal("expected task claim to be called")
	}
	if store.calledWith.AssignedAgentID != "agent-dispatch-1" {
		t.Fatalf("unexpected assigned agent id: %+v", store.calledWith)
	}
	if store.calledWith.LeaderEpoch != 11 {
		t.Fatalf("unexpected leader epoch: %+v", store.calledWith)
	}
	if store.last == nil {
		t.Fatal("expected outbox event")
	}
	if store.last.Topic != commands.AssignTaskOutboxTopic {
		t.Fatalf("unexpected topic: %+v", store.last)
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(store.last.Payload, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("unexpected task id: %+v", payload)
	}
	if payload.ExecutionID != "exec-dispatch-1" || payload.AgentID != "agent-dispatch-1" {
		t.Fatalf("unexpected execution payload: %+v", payload)
	}
	if payload.TaskKind != "PREDICTION" || payload.TaskType != "predict" {
		t.Fatalf("unexpected task metadata: %+v", payload)
	}
	if payload.Attempt != 1 || payload.MaxAttempts != 1 {
		t.Fatalf("unexpected attempts payload: %+v", payload)
	}
	if string(payload.ResolvedParams) != "{}" {
		t.Fatalf("unexpected resolved params: %s", string(payload.ResolvedParams))
	}
	if len(payload.DependsOnTaskIDs) != 0 {
		t.Fatalf("expected empty dependencies, got %+v", payload.DependsOnTaskIDs)
	}
	if payload.LeaderEpoch != 11 {
		t.Fatalf("unexpected leader epoch payload: %+v", payload)
	}
}

type fakeDispatchTaskStore struct {
	assignedTask *commands.ClaimedTask
	calledWith   *commands.AssignClaimParams
	last         *commands.OutboxEvent
}

func (f *fakeDispatchTaskStore) AssignPendingTask(_ context.Context, params commands.AssignClaimParams) (*commands.ClaimedTask, error) {
	f.calledWith = &params
	return f.assignedTask, nil
}

func (f *fakeDispatchTaskStore) Append(_ context.Context, event commands.OutboxEvent) error {
	f.last = &event
	return nil
}
