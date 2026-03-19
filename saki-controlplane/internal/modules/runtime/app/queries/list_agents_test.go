package queries

import (
	"context"
	"testing"
	"time"
)

func TestListRuntimeAgentsQueryReturnsAgentVocabulary(t *testing.T) {
	store := NewMemoryAdminStore()
	store.agents = []RuntimeAgent{
		{
			ID:         "agent-a",
			Version:    "1.2.3",
			LastSeenAt: time.UnixMilli(123456789),
		},
	}

	query := NewListAgentsQuery(store)
	agents, err := query.Execute(context.Background())
	if err != nil {
		t.Fatalf("execute list agents query: %v", err)
	}
	if len(agents) != 1 {
		t.Fatalf("unexpected agent count: %d", len(agents))
	}
	if agents[0].ID != "agent-a" || agents[0].Version != "1.2.3" {
		t.Fatalf("unexpected agent payload: %+v", agents[0])
	}
}
