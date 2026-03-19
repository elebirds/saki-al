package config

import (
	"encoding/json"
	"os"
	"strconv"
	"time"
)

const (
	defaultAgentControlBind       = ":18081"
	defaultAgentTransportMode     = "pull"
	defaultAgentID                = "agent-local"
	defaultAgentVersion           = "dev"
	defaultAgentMaxConcurrency    = 1
	defaultAgentHeartbeatInterval = 30 * time.Second
)

type Config struct {
	RuntimeBaseURL         string
	AgentControlBind       string
	AgentControlBaseURL    string
	AgentTransportMode     string
	AgentID                string
	AgentVersion           string
	AgentMaxConcurrency    int
	AgentHeartbeatInterval time.Duration
	AgentWorkerCommand     []string
}

func Load() (Config, error) {
	cfg := Config{
		RuntimeBaseURL:         os.Getenv("RUNTIME_BASE_URL"),
		AgentControlBind:       envOrDefault("AGENT_CONTROL_BIND", defaultAgentControlBind),
		AgentControlBaseURL:    os.Getenv("AGENT_CONTROL_BASE_URL"),
		AgentTransportMode:     envOrDefault("AGENT_TRANSPORT_MODE", defaultAgentTransportMode),
		AgentID:                envOrDefault("AGENT_ID", defaultAgentID),
		AgentVersion:           envOrDefault("AGENT_VERSION", defaultAgentVersion),
		AgentMaxConcurrency:    defaultAgentMaxConcurrency,
		AgentHeartbeatInterval: defaultAgentHeartbeatInterval,
		AgentWorkerCommand:     []string{},
	}

	if raw := os.Getenv("AGENT_HEARTBEAT_INTERVAL"); raw != "" {
		value, err := time.ParseDuration(raw)
		if err != nil {
			return Config{}, err
		}
		cfg.AgentHeartbeatInterval = value
	}

	if raw := os.Getenv("AGENT_MAX_CONCURRENCY"); raw != "" {
		value, err := strconv.Atoi(raw)
		if err != nil {
			return Config{}, err
		}
		cfg.AgentMaxConcurrency = normalizeMaxConcurrency(value)
	}

	if raw := os.Getenv("AGENT_WORKER_COMMAND_JSON"); raw != "" {
		var command []string
		if err := json.Unmarshal([]byte(raw), &command); err != nil {
			return Config{}, err
		}
		cfg.AgentWorkerCommand = command
	}

	return cfg, nil
}

func normalizeMaxConcurrency(value int) int {
	if value <= 0 {
		return 1
	}
	return value
}

func envOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
