package commands

import (
	"context"
	"slices"
	"time"
)

type ExecutorRecord struct {
	ID           string
	Version      string
	Capabilities []string
	LastSeenAt   time.Time
}

type RegisterExecutorCommand struct {
	ExecutorID   string
	Version      string
	Capabilities []string
	SeenAt       time.Time
}

type ExecutorRegistry interface {
	Register(ctx context.Context, executor ExecutorRecord) (*ExecutorRecord, error)
	Heartbeat(ctx context.Context, executorID string, seenAt time.Time) error
}

type RegisterExecutorHandler struct {
	registry ExecutorRegistry
	now      func() time.Time
}

func NewRegisterExecutorHandler(registry ExecutorRegistry) *RegisterExecutorHandler {
	return &RegisterExecutorHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *RegisterExecutorHandler) Handle(ctx context.Context, cmd RegisterExecutorCommand) (*ExecutorRecord, error) {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.Register(ctx, ExecutorRecord{
		ID:           cmd.ExecutorID,
		Version:      cmd.Version,
		Capabilities: slices.Clone(cmd.Capabilities),
		LastSeenAt:   seenAt,
	})
}
