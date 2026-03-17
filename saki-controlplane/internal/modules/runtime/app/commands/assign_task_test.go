package commands

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/google/uuid"
)

func TestAssignTaskCommandAssignsPendingTaskAndAppendsOutbox(t *testing.T) {
	taskID := uuid.New()
	store := &fakeAssignTaskStore{
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
	handler := NewAssignTaskHandler(store)
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
	if store.calledWith == nil {
		t.Fatal("expected claim repo to be called")
	}
	if store.calledWith.AssignedAgentID != "agent-1" || store.calledWith.LeaderEpoch != 7 {
		t.Fatalf("unexpected claim params: %+v", store.calledWith)
	}
	if store.last == nil || store.last.Topic != AssignTaskOutboxTopic {
		t.Fatalf("expected %s outbox event, got %+v", AssignTaskOutboxTopic, store.last)
	}
	if store.last.IdempotencyKey != AssignTaskOutboxTopic+":exec-1" {
		t.Fatalf("expected execution-scoped idempotency key, got %q", store.last.IdempotencyKey)
	}

	var payload AssignTaskOutboxPayload
	if err := json.Unmarshal(store.last.Payload, &payload); err != nil {
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

type fakeAssignTaskStore struct {
	assignedTask *ClaimedTask
	calledWith   *AssignClaimParams
	last         *OutboxEvent
}

func (f *fakeAssignTaskStore) AssignPendingTask(_ context.Context, params AssignClaimParams) (*ClaimedTask, error) {
	f.calledWith = &params
	return f.assignedTask, nil
}

func (f *fakeAssignTaskStore) Append(_ context.Context, event OutboxEvent) error {
	f.last = &event
	return nil
}

func TestAssignTaskCommandReturnsNilWhenNoPendingTaskClaimed(t *testing.T) {
	handler := NewAssignTaskHandler(&fakeAssignTaskStore{})

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

func (errTaskClaimer) Append(context.Context, OutboxEvent) error {
	return nil
}

func TestAssignTaskCommandReturnsClaimErrors(t *testing.T) {
	handler := NewAssignTaskHandler(errTaskClaimer{})

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

func TestAssignTaskCommandRejectsEmptyAssignedAgentID(t *testing.T) {
	store := &fakeAssignTaskStore{
		assignedTask: &ClaimedTask{
			ID:                 uuid.New(),
			CurrentExecutionID: "exec-1",
			AssignedAgentID:    "agent-1",
		},
	}
	handler := NewAssignTaskHandler(store)

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		AssignedAgentID: "",
		LeaderEpoch:     7,
	})
	if err == nil {
		t.Fatal("expected validation error for empty assigned agent id")
	}
	if assigned != nil {
		t.Fatalf("expected nil task on validation error, got %+v", assigned)
	}
	if store.calledWith != nil {
		t.Fatalf("expected claim repo not to be called, got %+v", store.calledWith)
	}
	if store.last != nil {
		t.Fatalf("expected outbox append not to be called, got %+v", store.last)
	}
}

type fakeOutboxWriter struct {
	last *OutboxEvent
}

func (f *fakeOutboxWriter) Append(_ context.Context, event OutboxEvent) error {
	f.last = &event
	return nil
}
