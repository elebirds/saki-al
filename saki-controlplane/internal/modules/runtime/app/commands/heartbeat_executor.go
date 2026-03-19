package commands

import (
	"context"
	"time"
)

type HeartbeatExecutorCommand struct {
	ExecutorID string
	SeenAt     time.Time
}

type HeartbeatAgentCommand struct {
	AgentID string
	SeenAt  time.Time
}

type HeartbeatAgentHandler struct {
	registry AgentRegistry
	now      func() time.Time
}

type HeartbeatExecutorHandler struct {
	registry ExecutorRegistry
	now      func() time.Time
}

func NewHeartbeatAgentHandler(registry AgentRegistry) *HeartbeatAgentHandler {
	return &HeartbeatAgentHandler{
		registry: registry,
		now:      time.Now,
	}
}

func NewHeartbeatExecutorHandler(registry ExecutorRegistry) *HeartbeatExecutorHandler {
	return &HeartbeatExecutorHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *HeartbeatAgentHandler) Handle(ctx context.Context, cmd HeartbeatAgentCommand) error {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.Heartbeat(ctx, cmd.AgentID, seenAt)
}

func (h *HeartbeatExecutorHandler) Handle(ctx context.Context, cmd HeartbeatExecutorCommand) error {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.Heartbeat(ctx, cmd.ExecutorID, seenAt)
}
