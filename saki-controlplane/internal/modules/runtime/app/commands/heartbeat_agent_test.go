package commands

import (
	"context"
	"slices"
	"testing"
	"time"
)

func TestHeartbeatAgentHandlerCarriesSchedulingFacts(t *testing.T) {
	registry := &fakeAgentRegistry{}
	handler := NewHeartbeatAgentHandler(registry)
	handler.now = func() time.Time { return time.UnixMilli(123456789) }

	if err := handler.Handle(context.Background(), HeartbeatAgentCommand{
		AgentID:        "agent-a",
		Version:        "1.2.4",
		RunningTaskIDs: []string{"task-1", "task-2"},
		MaxConcurrency: 0,
	}); err != nil {
		t.Fatalf("handle heartbeat agent: %v", err)
	}

	if registry.heartbeat == nil {
		t.Fatal("expected heartbeat to reach registry")
	}
	if registry.heartbeat.ID != "agent-a" || registry.heartbeat.Version != "1.2.4" {
		t.Fatalf("unexpected heartbeat payload: %+v", registry.heartbeat)
	}
	if !slices.Equal(registry.heartbeat.RunningTaskIDs, []string{"task-1", "task-2"}) {
		t.Fatalf("unexpected running task ids: %+v", registry.heartbeat)
	}
	if registry.heartbeat.MaxConcurrency != 1 {
		t.Fatalf("expected normalized max concurrency 1, got %+v", registry.heartbeat)
	}
	if !registry.heartbeat.LastSeenAt.Equal(time.UnixMilli(123456789)) {
		t.Fatalf("unexpected heartbeat last seen at: %s", registry.heartbeat.LastSeenAt)
	}
}

type fakeAgentRegistry struct {
	registered *AgentRecord
	heartbeat  *AgentHeartbeat
}

func (f *fakeAgentRegistry) RegisterAgent(_ context.Context, agent AgentRecord) (*AgentRecord, error) {
	f.registered = &agent
	return &agent, nil
}

func (f *fakeAgentRegistry) HeartbeatAgent(_ context.Context, heartbeat AgentHeartbeat) error {
	f.heartbeat = &heartbeat
	return nil
}
