package commands

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestAssignTaskHandler_AppendsAssignCommandInSameTx(t *testing.T) {
	taskID := uuid.New()
	store := &fakeAssignTaskStore{
		pendingTask: &PendingTask{
			ID:                   taskID,
			TaskKind:             "STEP",
			TaskType:             "predict",
			Attempt:              0,
			MaxAttempts:          3,
			ResolvedParams:       []byte(`{"prompt":"hello"}`),
			DependsOnTaskIDs:     []uuid.UUID{uuid.New()},
			RequiredCapabilities: []string{"gpu"},
		},
		agents: []AgentRecord{
			{
				ID:             "agent-1",
				Status:         "online",
				Capabilities:   []string{"gpu", "cuda"},
				TransportMode:  "pull",
				MaxConcurrency: 2,
				LastSeenAt:     time.Unix(123, 0),
			},
		},
	}
	selector := &fakeAssignTaskAgentSelector{
		selectedAgentID: "agent-1",
	}
	handler := NewAssignTaskHandler(store, selector)

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		LeaderEpoch: 7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}

	if assigned == nil || assigned.TaskID != taskID {
		t.Fatalf("unexpected assign result: %+v", assigned)
	}
	if assigned.AgentID != "agent-1" {
		t.Fatalf("expected selected agent agent-1, got %+v", assigned)
	}
	if assigned.AssignmentID == 0 {
		t.Fatalf("expected assignment id, got %+v", assigned)
	}
	if assigned.ExecutionID == "" {
		t.Fatalf("expected execution id, got %+v", assigned)
	}

	if selector.task == nil || selector.task.ID != taskID {
		t.Fatalf("expected selector to receive pending task, got %+v", selector.task)
	}
	if len(selector.agents) != 1 || selector.agents[0].ID != "agent-1" {
		t.Fatalf("expected selector to receive agent candidates, got %+v", selector.agents)
	}

	if store.assignment == nil {
		t.Fatal("expected assignment to be created")
	}
	if store.assignment.AgentID != "agent-1" || store.assignment.Status != "assigned" {
		t.Fatalf("unexpected assignment params: %+v", store.assignment)
	}
	if store.assignment.ExecutionID != assigned.ExecutionID {
		t.Fatalf("expected assignment execution id %q, got %+v", assigned.ExecutionID, store.assignment)
	}
	if store.assignment.Attempt != 1 {
		t.Fatalf("expected assignment attempt 1, got %+v", store.assignment)
	}

	if store.assignedTask == nil {
		t.Fatal("expected runtime task to be updated")
	}
	if store.assignedTask.AssignedAgentID != "agent-1" {
		t.Fatalf("unexpected assigned task params: %+v", store.assignedTask)
	}
	if store.assignedTask.ExecutionID != assigned.ExecutionID {
		t.Fatalf("expected assigned task execution id %q, got %+v", assigned.ExecutionID, store.assignedTask)
	}
	if store.assignedTask.Attempt != 1 || store.assignedTask.LeaderEpoch != 7 {
		t.Fatalf("unexpected assigned task params: %+v", store.assignedTask)
	}

	if store.command == nil {
		t.Fatal("expected agent command to be appended")
	}
	if store.command.AgentID != "agent-1" || store.command.TransportMode != "pull" {
		t.Fatalf("unexpected command params: %+v", store.command)
	}
	if store.command.AssignmentID != assigned.AssignmentID {
		t.Fatalf("expected command assignment id %d, got %+v", assigned.AssignmentID, store.command)
	}

	var payload AssignTaskCommandPayload
	if err := json.Unmarshal(store.command.Payload, &payload); err != nil {
		t.Fatalf("unmarshal command payload: %v", err)
	}
	if payload.TaskID != taskID {
		t.Fatalf("expected task id %s, got %s", taskID, payload.TaskID)
	}
	if payload.ExecutionID != assigned.ExecutionID {
		t.Fatalf("expected execution id %q, got %q", assigned.ExecutionID, payload.ExecutionID)
	}
	if payload.AgentID != "agent-1" {
		t.Fatalf("expected payload agent id agent-1, got %q", payload.AgentID)
	}
	if payload.TaskKind != "STEP" || payload.TaskType != "predict" {
		t.Fatalf("unexpected payload task metadata: %+v", payload)
	}
	if payload.Attempt != 1 || payload.MaxAttempts != 3 {
		t.Fatalf("unexpected payload attempt metadata: %+v", payload)
	}
	if string(payload.ResolvedParams) != `{"prompt":"hello"}` {
		t.Fatalf("unexpected resolved params payload: %s", string(payload.ResolvedParams))
	}
	if len(payload.DependsOnTaskIDs) != 1 {
		t.Fatalf("expected one dependency in payload, got %+v", payload.DependsOnTaskIDs)
	}
	if payload.LeaderEpoch != 7 {
		t.Fatalf("expected leader epoch 7, got %d", payload.LeaderEpoch)
	}

}

func TestAssignTaskHandler_ReturnsNilWhenNoPendingTaskClaimed(t *testing.T) {
	handler := NewAssignTaskHandler(&fakeAssignTaskStore{}, &fakeAssignTaskAgentSelector{})

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		LeaderEpoch: 7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}
	if assigned != nil {
		t.Fatalf("expected nil assigned task, got %+v", assigned)
	}
}

func TestAssignTaskHandler_ReturnsNilWhenNoAgentSelected(t *testing.T) {
	taskID := uuid.New()
	store := &fakeAssignTaskStore{
		pendingTask: &PendingTask{
			ID:       taskID,
			TaskKind: "STEP",
			TaskType: "predict",
		},
		agents: []AgentRecord{
			{
				ID:             "agent-full",
				Status:         "online",
				Capabilities:   []string{"gpu"},
				MaxConcurrency: 1,
				RunningTaskIDs: []string{"task-1"},
			},
		},
	}
	handler := NewAssignTaskHandler(store, &fakeAssignTaskAgentSelector{})

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		LeaderEpoch: 7,
	})
	if err != nil {
		t.Fatalf("handle assign task: %v", err)
	}
	if assigned != nil {
		t.Fatalf("expected nil assigned task, got %+v", assigned)
	}
	if store.assignment != nil || store.command != nil || store.assignedTask != nil {
		t.Fatalf("expected no side effects when selector returns nil, got assignment=%+v command=%+v assign=%+v", store.assignment, store.command, store.assignedTask)
	}
}

func TestAssignTaskHandler_ReturnsClaimErrors(t *testing.T) {
	handler := NewAssignTaskHandler(errAssignTaskStore{}, &fakeAssignTaskAgentSelector{})

	assigned, err := handler.Handle(context.Background(), AssignTaskCommand{
		LeaderEpoch: 7,
	})
	if err == nil {
		t.Fatal("expected claim error")
	}
	if assigned != nil {
		t.Fatalf("expected nil result on error, got %+v", assigned)
	}
}

type fakeAssignTaskStore struct {
	pendingTask  *PendingTask
	agents       []AgentRecord
	assignment   *CreateTaskAssignmentParams
	assignedTask *AssignClaimedTaskParams
	command      *AppendAssignTaskCommandParams
	assignmentID int64
	commandID    uuid.UUID
}

func (f *fakeAssignTaskStore) ClaimPendingTask(context.Context) (*PendingTask, error) {
	return f.pendingTask, nil
}

func (f *fakeAssignTaskStore) ListAssignableAgents(context.Context) ([]AgentRecord, error) {
	return append([]AgentRecord(nil), f.agents...), nil
}

func (f *fakeAssignTaskStore) CreateTaskAssignment(_ context.Context, params CreateTaskAssignmentParams) (*TaskAssignmentRecord, error) {
	f.assignment = &params
	f.assignmentID = 41
	return &TaskAssignmentRecord{
		ID:          f.assignmentID,
		TaskID:      params.TaskID,
		Attempt:     params.Attempt,
		AgentID:     params.AgentID,
		ExecutionID: params.ExecutionID,
		Status:      params.Status,
	}, nil
}

func (f *fakeAssignTaskStore) AssignClaimedTask(_ context.Context, params AssignClaimedTaskParams) (*ClaimedTask, error) {
	f.assignedTask = &params
	return &ClaimedTask{
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

func (f *fakeAssignTaskStore) AppendAssignCommand(_ context.Context, params AppendAssignTaskCommandParams) error {
	f.command = &params
	f.commandID = params.CommandID
	return nil
}

type fakeAssignTaskAgentSelector struct {
	selectedAgentID string
	task            *PendingTask
	agents          []AgentRecord
}

func (f *fakeAssignTaskAgentSelector) SelectAgent(task PendingTask, agents []AgentRecord) *AgentRecord {
	taskCopy := task
	f.task = &taskCopy
	f.agents = append([]AgentRecord(nil), agents...)
	if f.selectedAgentID == "" {
		return nil
	}
	for i := range agents {
		if agents[i].ID == f.selectedAgentID {
			agent := agents[i]
			return &agent
		}
	}
	return nil
}

type errAssignTaskStore struct{}

func (errAssignTaskStore) ClaimPendingTask(context.Context) (*PendingTask, error) {
	return nil, context.DeadlineExceeded
}

func (errAssignTaskStore) ListAssignableAgents(context.Context) ([]AgentRecord, error) {
	return nil, nil
}

func (errAssignTaskStore) CreateTaskAssignment(context.Context, CreateTaskAssignmentParams) (*TaskAssignmentRecord, error) {
	return nil, nil
}

func (errAssignTaskStore) AssignClaimedTask(context.Context, AssignClaimedTaskParams) (*ClaimedTask, error) {
	return nil, nil
}

func (errAssignTaskStore) AppendAssignCommand(context.Context, AppendAssignTaskCommandParams) error {
	return nil
}
