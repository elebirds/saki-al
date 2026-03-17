package commands

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/google/uuid"
)

func TestAssignTaskCommandAssignsPendingTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	taskStore := &fakeTaskClaimer{
		assignedTask: &ClaimedTask{
			ID:                 taskID,
			TaskKind:           "STEP",
			TaskType:           "predict",
			CurrentExecutionID: "exec-1",
			AssignedAgentID:    "agent-1",
			Attempt:            1,
			MaxAttempts:        3,
			ResolvedParams:     []byte(`{"prompt":"hello"}`),
			LeaderEpoch:        7,
		},
	}
	outbox := &fakeOutboxWriter{}

	handler := NewAssignTaskHandler(taskStore, outbox)
	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		AssignedAgentID: "agent-1",
		LeaderEpoch:     7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}

	if assigned == nil || assigned.ID != taskID {
		t.Fatalf("unexpected assigned task: %+v", assigned)
	}
	if taskStore.calledWith == nil {
		t.Fatal("expected claim repo to be called")
	}
	if taskStore.calledWith.AssignedAgentID != "agent-1" || taskStore.calledWith.LeaderEpoch != 7 {
		t.Fatalf("unexpected claim params: %+v", taskStore.calledWith)
	}
	if outbox.last == nil || outbox.last.Topic != AssignTaskOutboxTopic {
		t.Fatalf("expected %s outbox event, got %+v", AssignTaskOutboxTopic, outbox.last)
	}
	if outbox.last.IdempotencyKey != AssignTaskOutboxTopic+":exec-1" {
		t.Fatalf("expected execution-scoped idempotency key, got %q", outbox.last.IdempotencyKey)
	}

	var payload AssignTaskOutboxPayload
	if err := json.Unmarshal(outbox.last.Payload, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("expected task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != "exec-1" {
		t.Fatalf("expected execution id exec-1, got %q", payload.ExecutionID)
	}
	if payload.AgentID != "agent-1" {
		t.Fatalf("expected agent id agent-1, got %q", payload.AgentID)
	}
	if payload.TaskKind != "STEP" || payload.TaskType != "predict" {
		t.Fatalf("unexpected task kind/type payload: %+v", payload)
	}
	if payload.Attempt != 1 || payload.MaxAttempts != 3 {
		t.Fatalf("unexpected attempt payload: %+v", payload)
	}
	if string(payload.ResolvedParams) != `{"prompt":"hello"}` {
		t.Fatalf("unexpected resolved params payload: %s", string(payload.ResolvedParams))
	}
	if len(payload.DependsOnTaskIDs) != 0 {
		t.Fatalf("expected empty depends_on_task_ids, got %+v", payload.DependsOnTaskIDs)
	}
	if payload.LeaderEpoch != 7 {
		t.Fatalf("expected leader epoch 7, got %d", payload.LeaderEpoch)
	}
}

type fakeTaskClaimer struct {
	assignedTask *ClaimedTask
	calledWith   *AssignClaimParams
}

func (f *fakeTaskClaimer) AssignPendingTask(_ context.Context, params AssignClaimParams) (*ClaimedTask, error) {
	f.calledWith = &params
	return f.assignedTask, nil
}

func TestAssignTaskCommandReturnsNilWhenNoPendingTaskClaimed(t *testing.T) {
	handler := NewAssignTaskHandler(&fakeTaskClaimer{}, &fakeOutboxWriter{})

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		AssignedAgentID: "agent-1",
		LeaderEpoch:     7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}
	if assigned != nil {
		t.Fatalf("expected nil assigned task, got %+v", assigned)
	}
}

type errTaskClaimer struct{}

func (errTaskClaimer) AssignPendingTask(context.Context, AssignClaimParams) (*ClaimedTask, error) {
	return nil, context.DeadlineExceeded
}

func TestAssignTaskCommandReturnsClaimErrors(t *testing.T) {
	handler := NewAssignTaskHandler(errTaskClaimer{}, &fakeOutboxWriter{})

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		AssignedAgentID: "agent-1",
		LeaderEpoch:     7,
	})
	if err == nil {
		t.Fatal("expected claim error")
	}
	if assigned != nil {
		t.Fatalf("expected nil task on error, got %+v", assigned)
	}
}

type fakeOutboxWriter struct {
	last *OutboxEvent
}

func (f *fakeOutboxWriter) Append(_ context.Context, event OutboxEvent) error {
	f.last = &event
	return nil
}
