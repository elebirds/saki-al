package commands

import (
	"context"
	"errors"
	"slices"
	"time"
)

const (
	DefaultAgentTransportMode  = "pull"
	DefaultAgentMaxConcurrency = int32(1)
)

var ErrDirectAgentControlBaseURLRequired = errors.New("direct transport requires control_base_url")

type AgentRecord struct {
	ID             string
	Version        string
	Capabilities   []string
	TransportMode  string
	ControlBaseURL string
	MaxConcurrency int32
	RunningTaskIDs []string
	LastSeenAt     time.Time
}

type AgentHeartbeat struct {
	ID             string
	Version        string
	RunningTaskIDs []string
	MaxConcurrency int32
	LastSeenAt     time.Time
}

type RegisterAgentCommand struct {
	AgentID        string
	Version        string
	Capabilities   []string
	TransportMode  string
	ControlBaseURL string
	MaxConcurrency int32
	SeenAt         time.Time
}

// AgentRegistry 只接收 agent 主动上报的调度事实，不把连接会话本身当成注册真相。
type AgentRegistry interface {
	RegisterAgent(ctx context.Context, agent AgentRecord) (*AgentRecord, error)
	HeartbeatAgent(ctx context.Context, heartbeat AgentHeartbeat) error
}

type RegisterAgentHandler struct {
	registry AgentRegistry
	now      func() time.Time
}

func NewRegisterAgentHandler(registry AgentRegistry) *RegisterAgentHandler {
	return &RegisterAgentHandler{
		registry: registry,
		now:      time.Now,
	}
}

func (h *RegisterAgentHandler) Handle(ctx context.Context, cmd RegisterAgentCommand) (*AgentRecord, error) {
	seenAt := cmd.SeenAt
	if seenAt.IsZero() {
		seenAt = h.now()
	}

	transportMode := normalizeAgentTransportMode(cmd.TransportMode)
	controlBaseURL := cmd.ControlBaseURL
	maxConcurrency := normalizeAgentMaxConcurrency(cmd.MaxConcurrency)
	// direct 只有在显式上报可达控制地址时才能进入主路径；pull/relay 不依赖这个入口。
	if transportMode == "direct" && controlBaseURL == "" {
		return nil, ErrDirectAgentControlBaseURLRequired
	}

	return h.registry.RegisterAgent(ctx, AgentRecord{
		ID:             cmd.AgentID,
		Version:        cmd.Version,
		Capabilities:   slices.Clone(cmd.Capabilities),
		TransportMode:  transportMode,
		ControlBaseURL: controlBaseURL,
		MaxConcurrency: maxConcurrency,
		LastSeenAt:     seenAt,
	})
}

func normalizeAgentTransportMode(mode string) string {
	if mode == "" {
		return DefaultAgentTransportMode
	}
	return mode
}

func normalizeAgentMaxConcurrency(maxConcurrency int32) int32 {
	if maxConcurrency <= 0 {
		return DefaultAgentMaxConcurrency
	}
	return maxConcurrency
}
