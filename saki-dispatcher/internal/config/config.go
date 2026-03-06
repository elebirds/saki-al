package config

import (
	"fmt"
	"strings"

	"github.com/caarlos0/env/v11"
)

type Config struct {
	RuntimeGRPCBind string `env:"RUNTIME_GRPC_BIND" envDefault:"0.0.0.0:50051"`
	AdminGRPCBind   string `env:"ADMIN_GRPC_BIND" envDefault:"0.0.0.0:50052"`

	DatabaseURL string `env:"DATABASE_URL" envDefault:"postgresql://postgres:postgres@localhost:5432/saki"`

	InternalToken string `env:"INTERNAL_TOKEN" envDefault:"dev-secret"`
	LogLevel      string `env:"LOG_LEVEL" envDefault:"info"`

	EnableStdinCommands bool `env:"ENABLE_STDIN_COMMANDS" envDefault:"true"`

	HeartbeatTimeoutSec        int   `env:"RUNTIME_HEARTBEAT_TIMEOUT_SEC" envDefault:"30"`
	DispatchIntervalSec        int   `env:"DISPATCH_SCAN_INTERVAL_SEC" envDefault:"3"`
	SimulationRoundCooldownSec int   `env:"SIMULATION_ROUND_COOLDOWN_SEC" envDefault:"5"`
	StoppingForceCancelSec     int   `env:"STOPPING_FORCE_CANCEL_SEC" envDefault:"120"`
	InFlightPreRunTimeoutSec   int   `env:"TASK_INFLIGHT_PRERUN_TIMEOUT_SEC" envDefault:"120"`
	InFlightRunningTimeoutSec  int   `env:"TASK_INFLIGHT_RUNNING_TIMEOUT_SEC" envDefault:"120"`
	PredictionTTLDays          int   `env:"PREDICTION_TTL_DAYS" envDefault:"0"`
	PredictionTTLKeepRounds    int   `env:"PREDICTION_TTL_KEEP_ROUNDS" envDefault:"2"`
	AssignAckTimeoutSec        int   `env:"ASSIGN_ACK_TIMEOUT_SEC" envDefault:"30"`
	DispatchScanLockKey        int64 `env:"DISPATCH_SCAN_LOCK_KEY" envDefault:"8042002"`
	RoundAffinityWaitSec       int   `env:"ROUND_AFFINITY_WAIT_SEC" envDefault:"20"`
	StrictTrainModelHandoff    bool  `env:"STRICT_TRAIN_MODEL_HANDOFF" envDefault:"true"`

	RuntimeDomainTarget string `env:"RUNTIME_DOMAIN_TARGET" envDefault:"localhost:50053"`
	RuntimeDomainToken  string `env:"RUNTIME_DOMAIN_TOKEN" envDefault:"dev-secret"`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, fmt.Errorf("解析环境变量失败: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.RuntimeGRPCBind) == "" {
		return fmt.Errorf("RUNTIME_GRPC_BIND 不能为空")
	}
	if strings.TrimSpace(c.AdminGRPCBind) == "" {
		return fmt.Errorf("ADMIN_GRPC_BIND 不能为空")
	}
	if c.HeartbeatTimeoutSec <= 0 {
		return fmt.Errorf("RUNTIME_HEARTBEAT_TIMEOUT_SEC 必须大于 0")
	}
	if c.AssignAckTimeoutSec <= 0 {
		return fmt.Errorf("ASSIGN_ACK_TIMEOUT_SEC 必须大于 0")
	}
	if c.DispatchIntervalSec <= 0 {
		return fmt.Errorf("DISPATCH_SCAN_INTERVAL_SEC 必须大于 0")
	}
	if c.SimulationRoundCooldownSec < 0 {
		return fmt.Errorf("SIMULATION_ROUND_COOLDOWN_SEC 必须大于等于 0")
	}
	if c.StoppingForceCancelSec < 0 {
		return fmt.Errorf("STOPPING_FORCE_CANCEL_SEC 必须大于等于 0")
	}
	if c.InFlightPreRunTimeoutSec <= 0 {
		return fmt.Errorf("TASK_INFLIGHT_PRERUN_TIMEOUT_SEC 必须大于 0")
	}
	if c.InFlightRunningTimeoutSec <= 0 {
		return fmt.Errorf("TASK_INFLIGHT_RUNNING_TIMEOUT_SEC 必须大于 0")
	}
	if c.PredictionTTLDays < 0 {
		return fmt.Errorf("PREDICTION_TTL_DAYS 必须大于等于 0")
	}
	if c.PredictionTTLKeepRounds < 0 {
		return fmt.Errorf("PREDICTION_TTL_KEEP_ROUNDS 必须大于等于 0")
	}
	if c.RoundAffinityWaitSec < 0 {
		return fmt.Errorf("ROUND_AFFINITY_WAIT_SEC 必须大于等于 0")
	}
	return nil
}
