package commands

import (
	"context"
	"slices"
	"time"
)

type HeartbeatAgentCommand struct {
	AgentID        string
	Version        string
	RunningTaskIDs []string
	MaxConcurrency int32
	SeenAt         time.Time
}

type HeartbeatAgentHandler struct {
	registry AgentRegistry
	now      func() time.Time
}

func NewHeartbeatAgentHandler(registry AgentRegistry) *HeartbeatAgentHandler {
	return &HeartbeatAgentHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *HeartbeatAgentHandler) Handle(ctx context.Context, cmd HeartbeatAgentCommand) error {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.HeartbeatAgent(ctx, AgentHeartbeat{
		ID:             cmd.AgentID,
		Version:        cmd.Version,
		RunningTaskIDs: slices.Clone(cmd.RunningTaskIDs),
		MaxConcurrency: normalizeAgentMaxConcurrency(cmd.MaxConcurrency),
		LastSeenAt:     seenAt,
	})
}
