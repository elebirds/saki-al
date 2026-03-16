package commands

import (
	"context"
	"time"
)

type HeartbeatExecutorCommand struct {
	ExecutorID string
	SeenAt     time.Time
}

type HeartbeatExecutorHandler struct {
	registry ExecutorRegistry
	now      func() time.Time
}

func NewHeartbeatExecutorHandler(registry ExecutorRegistry) *HeartbeatExecutorHandler {
	return &HeartbeatExecutorHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *HeartbeatExecutorHandler) Handle(ctx context.Context, cmd HeartbeatExecutorCommand) error {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.Heartbeat(ctx, cmd.ExecutorID, seenAt)
}
