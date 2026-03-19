package scheduler

import (
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

func TestAgentSelector_PrefersCapacityThenFreshnessThenID(t *testing.T) {
	selector := NewAgentSelector()
	now := time.Unix(1_700_000_000, 0)

	selected := selector.SelectAgent(commands.PendingTask{
		ID:                   uuid.New(),
		TaskType:             "predict",
		RequiredCapabilities: []string{"gpu"},
	}, []commands.AgentRecord{
		{
			ID:             "agent-busy",
			Status:         "online",
			Capabilities:   []string{"gpu"},
			MaxConcurrency: 1,
			RunningTaskIDs: []string{"task-1"},
			LastSeenAt:     now,
		},
		{
			ID:             "agent-fresh-b",
			Status:         "online",
			Capabilities:   []string{"gpu"},
			MaxConcurrency: 3,
			RunningTaskIDs: []string{"task-1"},
			LastSeenAt:     now,
		},
		{
			ID:             "agent-fresh-a",
			Status:         "online",
			Capabilities:   []string{"gpu"},
			MaxConcurrency: 3,
			RunningTaskIDs: []string{"task-1"},
			LastSeenAt:     now,
		},
		{
			ID:             "agent-stale",
			Status:         "online",
			Capabilities:   []string{"gpu"},
			MaxConcurrency: 3,
			RunningTaskIDs: []string{"task-1"},
			LastSeenAt:     now.Add(-time.Minute),
		},
		{
			ID:             "agent-offline",
			Status:         "offline",
			Capabilities:   []string{"gpu"},
			MaxConcurrency: 10,
			LastSeenAt:     now,
		},
		{
			ID:             "agent-missing-capability",
			Status:         "online",
			Capabilities:   []string{"cpu"},
			MaxConcurrency: 10,
			LastSeenAt:     now,
		},
	})

	if selected == nil {
		t.Fatal("expected an available agent to be selected")
	}
	if selected.ID != "agent-fresh-a" {
		t.Fatalf("expected tie to break by id after freshness, got %+v", selected)
	}
}

func TestAgentSelector_ReturnsNilWhenTaskRequirementsCannotBeMet(t *testing.T) {
	selector := NewAgentSelector()

	selected := selector.SelectAgent(commands.PendingTask{
		ID:                   uuid.New(),
		TaskType:             "predict",
		RequiredCapabilities: []string{"gpu"},
	}, []commands.AgentRecord{
		{
			ID:             "agent-cpu",
			Status:         "online",
			Capabilities:   []string{"cpu"},
			MaxConcurrency: 2,
			LastSeenAt:     time.Unix(1_700_000_000, 0),
		},
	})

	if selected != nil {
		t.Fatalf("expected no agent to be selected, got %+v", selected)
	}
}
