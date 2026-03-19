package scheduler

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

func TestDispatchScan_SelectsBestAgentAndCreatesAssignment(t *testing.T) {
	taskID := uuid.New()
	store := &fakeDispatchTaskStore{
		pendingTask: &commands.PendingTask{
			ID:                   taskID,
			TaskKind:             "PREDICTION",
			TaskType:             "predict",
			MaxAttempts:          1,
			ResolvedParams:       []byte(`{}`),
			RequiredCapabilities: []string{"gpu"},
		},
		agents: []commands.AgentRecord{
			{
				ID:             "agent-offline",
				Status:         "offline",
				Capabilities:   []string{"gpu"},
				TransportMode:  "direct",
				MaxConcurrency: 8,
				LastSeenAt:     time.Unix(300, 0),
			},
			{
				ID:             "agent-fresh",
				Status:         "online",
				Capabilities:   []string{"gpu"},
				TransportMode:  "pull",
				MaxConcurrency: 3,
				RunningTaskIDs: []string{"task-1"},
				LastSeenAt:     time.Unix(200, 0),
			},
			{
				ID:             "agent-stale",
				Status:         "online",
				Capabilities:   []string{"gpu"},
				TransportMode:  "direct",
				MaxConcurrency: 3,
				RunningTaskIDs: []string{"task-1"},
				LastSeenAt:     time.Unix(100, 0),
			},
			{
				ID:             "agent-missing-capability",
				Status:         "online",
				Capabilities:   []string{"cpu"},
				TransportMode:  "pull",
				MaxConcurrency: 6,
				LastSeenAt:     time.Unix(500, 0),
			},
		},
	}
	assigner := commands.NewAssignTaskHandler(store, NewAgentSelector())
	scan := NewDispatchScan(assigner)

	if err := scan.Dispatch(context.Background(), DispatchCommand{LeaderEpoch: 11}); err != nil {
		t.Fatalf("dispatch scan: %v", err)
	}

	if store.assignment == nil {
		t.Fatal("expected assignment to be created")
	}
	if store.assignment.AgentID != "agent-fresh" {
		t.Fatalf("expected best agent agent-fresh, got %+v", store.assignment)
	}
	if store.assignedTask == nil || store.assignedTask.AssignedAgentID != "agent-fresh" {
		t.Fatalf("expected runtime task to be assigned to agent-fresh, got %+v", store.assignedTask)
	}
	if store.command == nil || store.command.TransportMode != "pull" {
		t.Fatalf("expected assign command to inherit selected transport mode, got %+v", store.command)
	}
	if store.lastOutbox == nil || store.lastOutbox.Topic != commands.AssignTaskOutboxTopic {
		t.Fatalf("expected legacy outbox compatibility write, got %+v", store.lastOutbox)
	}

	var payload commands.AssignTaskOutboxPayload
	if err := json.Unmarshal(store.command.Payload, &payload); err != nil {
		t.Fatalf("unmarshal command payload: %v", err)
	}
	if payload.TaskID != taskID || payload.AgentID != "agent-fresh" {
		t.Fatalf("unexpected command payload: %+v", payload)
	}
	if payload.LeaderEpoch != 11 {
		t.Fatalf("expected leader epoch 11, got %+v", payload)
	}
}

func TestDispatchScan_DoesNothingWhenNoAgentIsAvailable(t *testing.T) {
	store := &fakeDispatchTaskStore{
		pendingTask: &commands.PendingTask{
			ID:                   uuid.New(),
			TaskKind:             "PREDICTION",
			TaskType:             "predict",
			RequiredCapabilities: []string{"gpu"},
		},
		agents: []commands.AgentRecord{
			{
				ID:             "agent-full",
				Status:         "online",
				Capabilities:   []string{"gpu"},
				MaxConcurrency: 1,
				RunningTaskIDs: []string{"task-1"},
			},
		},
	}
	assigner := commands.NewAssignTaskHandler(store, NewAgentSelector())
	scan := NewDispatchScan(assigner)

	if err := scan.Dispatch(context.Background(), DispatchCommand{LeaderEpoch: 17}); err != nil {
		t.Fatalf("dispatch scan: %v", err)
	}
	if store.assignment != nil || store.command != nil || store.lastOutbox != nil || store.assignedTask != nil {
		t.Fatalf("expected no side effects when no agent is available, got assignment=%+v command=%+v outbox=%+v assigned=%+v", store.assignment, store.command, store.lastOutbox, store.assignedTask)
	}
}

type fakeDispatchTaskStore struct {
	pendingTask  *commands.PendingTask
	agents       []commands.AgentRecord
	assignment   *commands.CreateTaskAssignmentParams
	assignedTask *commands.AssignClaimedTaskParams
	command      *commands.AppendAssignTaskCommandParams
	lastOutbox   *commands.OutboxEvent
}

func (f *fakeDispatchTaskStore) ClaimPendingTask(context.Context) (*commands.PendingTask, error) {
	return f.pendingTask, nil
}

func (f *fakeDispatchTaskStore) ListAssignableAgents(context.Context) ([]commands.AgentRecord, error) {
	return append([]commands.AgentRecord(nil), f.agents...), nil
}

func (f *fakeDispatchTaskStore) CreateTaskAssignment(_ context.Context, params commands.CreateTaskAssignmentParams) (*commands.TaskAssignmentRecord, error) {
	f.assignment = &params
	return &commands.TaskAssignmentRecord{
		ID:          64,
		TaskID:      params.TaskID,
		Attempt:     params.Attempt,
		AgentID:     params.AgentID,
		ExecutionID: params.ExecutionID,
		Status:      params.Status,
	}, nil
}

func (f *fakeDispatchTaskStore) AssignClaimedTask(_ context.Context, params commands.AssignClaimedTaskParams) (*commands.ClaimedTask, error) {
	f.assignedTask = &params
	return &commands.ClaimedTask{
		ID:                 params.TaskID,
		TaskKind:           f.pendingTask.TaskKind,
		TaskType:           f.pendingTask.TaskType,
		Status:             "assigned",
		CurrentExecutionID: params.ExecutionID,
		AssignedAgentID:    params.AssignedAgentID,
		Attempt:            params.Attempt,
		MaxAttempts:        f.pendingTask.MaxAttempts,
		ResolvedParams:     append([]byte(nil), f.pendingTask.ResolvedParams...),
		DependsOnTaskIDs:   append([]uuid.UUID(nil), f.pendingTask.DependsOnTaskIDs...),
		LeaderEpoch:        params.LeaderEpoch,
	}, nil
}

func (f *fakeDispatchTaskStore) AppendAssignCommand(_ context.Context, params commands.AppendAssignTaskCommandParams) error {
	f.command = &params
	return nil
}

func (f *fakeDispatchTaskStore) Append(_ context.Context, event commands.OutboxEvent) error {
	f.lastOutbox = &event
	return nil
}
