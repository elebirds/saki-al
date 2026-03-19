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

type AgentRecord = ExecutorRecord

type RegisterAgentCommand struct {
	AgentID      string
	Version      string
	Capabilities []string
	SeenAt       time.Time
}

type RegisterExecutorCommand struct {
	ExecutorID   string
	Version      string
	Capabilities []string
	SeenAt       time.Time
}

type AgentRegistry interface {
	Register(ctx context.Context, agent AgentRecord) (*AgentRecord, error)
	Heartbeat(ctx context.Context, agentID string, seenAt time.Time) error
}

type ExecutorRegistry = AgentRegistry

type RegisterAgentHandler struct {
	registry AgentRegistry
	now      func() time.Time
}

type RegisterExecutorHandler struct {
	registry ExecutorRegistry
	now      func() time.Time
}

func NewRegisterAgentHandler(registry AgentRegistry) *RegisterAgentHandler {
	return &RegisterAgentHandler{
		registry: registry,
		now:      time.Now,
	}
}

func NewRegisterExecutorHandler(registry ExecutorRegistry) *RegisterExecutorHandler {
	return &RegisterExecutorHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *RegisterAgentHandler) Handle(ctx context.Context, cmd RegisterAgentCommand) (*AgentRecord, error) {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	return h.registry.Register(ctx, AgentRecord{
		ID:           cmd.AgentID,
		Version:      cmd.Version,
		Capabilities: slices.Clone(cmd.Capabilities),
		LastSeenAt:   seenAt,
	})
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
