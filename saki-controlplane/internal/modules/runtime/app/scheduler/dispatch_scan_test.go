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
	taskClaimer := &fakeDispatchTaskClaimer{
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
	outbox := &fakeDispatchOutboxWriter{}
	handler := commands.NewAssignTaskHandler(taskClaimer, outbox)
	scan := NewDispatchScan(handler, "agent-dispatch-1")

	if err := scan.Dispatch(context.Background(), DispatchCommand{LeaderEpoch: 11}); err != nil {
		t.Fatalf("dispatch scan: %v", err)
	}

	if taskClaimer.calledWith == nil {
		t.Fatal("expected task claim to be called")
	}
	if taskClaimer.calledWith.AssignedAgentID != "agent-dispatch-1" {
		t.Fatalf("unexpected assigned agent id: %+v", taskClaimer.calledWith)
	}
	if taskClaimer.calledWith.LeaderEpoch != 11 {
		t.Fatalf("unexpected leader epoch: %+v", taskClaimer.calledWith)
	}
	if outbox.last == nil {
		t.Fatal("expected outbox event")
	}
	if outbox.last.Topic != commands.AssignTaskOutboxTopic {
		t.Fatalf("unexpected topic: %+v", outbox.last)
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(outbox.last.Payload, &payload); err != nil {
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

type fakeDispatchTaskClaimer struct {
	assignedTask *commands.ClaimedTask
	calledWith   *commands.AssignClaimParams
}

func (f *fakeDispatchTaskClaimer) AssignPendingTask(_ context.Context, params commands.AssignClaimParams) (*commands.ClaimedTask, error) {
	f.calledWith = &params
	return f.assignedTask, nil
}

type fakeDispatchOutboxWriter struct {
	last *commands.OutboxEvent
}

func (f *fakeDispatchOutboxWriter) Append(_ context.Context, event commands.OutboxEvent) error {
	f.last = &event
	return nil
}
