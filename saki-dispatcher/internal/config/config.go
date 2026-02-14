package config

import (
	"fmt"
	"strings"

	"github.com/caarlos0/env/v11"
)

type Config struct {
	RuntimeGRPCBind string `env:"RUNTIME_GRPC_BIND" envDefault:"0.0.0.0:50051"`
	AdminGRPCBind   string `env:"ADMIN_GRPC_BIND" envDefault:"0.0.0.0:50052"`

	DatabaseURL string `env:"DATABASE_URL" envDefault:""`

	InternalToken string `env:"INTERNAL_TOKEN" envDefault:"dev-secret"`
	LogLevel      string `env:"LOG_LEVEL" envDefault:"info"`

	HeartbeatTimeoutSec        int   `env:"RUNTIME_HEARTBEAT_TIMEOUT_SEC" envDefault:"30"`
	DispatchIntervalSec        int   `env:"DISPATCH_SCAN_INTERVAL_SEC" envDefault:"3"`
	SimulationRoundCooldownSec int   `env:"SIMULATION_ROUND_COOLDOWN_SEC" envDefault:"5"`
	AssignAckTimeoutSec        int   `env:"ASSIGN_ACK_TIMEOUT_SEC" envDefault:"30"`
	DispatchScanLockKey        int64 `env:"DISPATCH_SCAN_LOCK_KEY" envDefault:"8042002"`

	RuntimeDomainTarget string `env:"RUNTIME_DOMAIN_TARGET" envDefault:""`
	RuntimeDomainToken  string `env:"RUNTIME_DOMAIN_TOKEN" envDefault:""`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, fmt.Errorf("parse env: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.RuntimeGRPCBind) == "" {
		return fmt.Errorf("RUNTIME_GRPC_BIND is required")
	}
	if strings.TrimSpace(c.AdminGRPCBind) == "" {
		return fmt.Errorf("ADMIN_GRPC_BIND is required")
	}
	if c.HeartbeatTimeoutSec <= 0 {
		return fmt.Errorf("RUNTIME_HEARTBEAT_TIMEOUT_SEC must be > 0")
	}
	if c.AssignAckTimeoutSec <= 0 {
		return fmt.Errorf("ASSIGN_ACK_TIMEOUT_SEC must be > 0")
	}
	if c.DispatchIntervalSec <= 0 {
		return fmt.Errorf("DISPATCH_SCAN_INTERVAL_SEC must be > 0")
	}
	if c.SimulationRoundCooldownSec < 0 {
		return fmt.Errorf("SIMULATION_ROUND_COOLDOWN_SEC must be >= 0")
	}
	return nil
}
