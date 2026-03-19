package config

import (
	"encoding/json"
	"os"
	"time"
)

const (
	defaultAgentControlBind       = ":18081"
	defaultAgentID                = "agent-local"
	defaultAgentVersion           = "dev"
	defaultAgentHeartbeatInterval = 30 * time.Second
)

type Config struct {
	RuntimeBaseURL         string
	AgentControlBind       string
	AgentID                string
	AgentVersion           string
	AgentHeartbeatInterval time.Duration
	AgentWorkerCommand     []string
}

func Load() (Config, error) {
	cfg := Config{
		RuntimeBaseURL:         os.Getenv("RUNTIME_BASE_URL"),
		AgentControlBind:       envOrDefault("AGENT_CONTROL_BIND", defaultAgentControlBind),
		AgentID:                envOrDefault("AGENT_ID", defaultAgentID),
		AgentVersion:           envOrDefault("AGENT_VERSION", defaultAgentVersion),
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

	if raw := os.Getenv("AGENT_WORKER_COMMAND_JSON"); raw != "" {
		var command []string
		if err := json.Unmarshal([]byte(raw), &command); err != nil {
			return Config{}, err
		}
		cfg.AgentWorkerCommand = command
	}

	return cfg, nil
}

func envOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
