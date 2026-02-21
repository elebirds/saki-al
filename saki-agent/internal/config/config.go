package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/caarlos0/env/v11"
)

type Config struct {
	RunDir              string `env:"SAKI_AGENT_RUN_DIR"`
	CacheDir            string `env:"SAKI_AGENT_CACHE_DIR"`
	KernelsDir          string `env:"SAKI_AGENT_KERNELS_DIR"`
	LogLevel            string `env:"LOG_LEVEL" envDefault:"info"`
	EnableStdinCommands bool   `env:"ENABLE_STDIN_COMMANDS" envDefault:"true"`

	RuntimeControlTarget string `env:"RUNTIME_CONTROL_TARGET" envDefault:"127.0.0.1:50051"`
	InternalToken        string `env:"INTERNAL_TOKEN" envDefault:"dev-secret"`
	// ExecutorID: 执行实例 ID（dispatcher 侧调度主键）。
	// 建议在单实例 agent 场景保持稳定，不要频繁变更。
	ExecutorID string `env:"SAKI_AGENT_EXECUTOR_ID" envDefault:""`
	// NodeID: 节点 ID（物理/逻辑主机标识，支持多个 executor 共享）。
	// 主要用于节点归属与观测，不作为调度主键。
	NodeID                     string `env:"SAKI_AGENT_NODE_ID" envDefault:""`
	RuntimeKind                string `env:"SAKI_AGENT_RUNTIME_KIND" envDefault:"saki-agent"`
	Version                    string `env:"SAKI_AGENT_VERSION" envDefault:"dev"`
	HeartbeatIntervalSec       int    `env:"SAKI_AGENT_HEARTBEAT_INTERVAL_SEC" envDefault:"10"`
	ConnectTimeoutSec          int    `env:"SAKI_AGENT_CONNECT_TIMEOUT_SEC" envDefault:"5"`
	ReconnectInitialBackoffSec int    `env:"SAKI_AGENT_RECONNECT_INITIAL_BACKOFF_SEC" envDefault:"2"`
	ReconnectMaxBackoffSec     int    `env:"SAKI_AGENT_RECONNECT_MAX_BACKOFF_SEC" envDefault:"30"`

	MinIOEndpoint  string `env:"SAKI_AGENT_MINIO_ENDPOINT"`
	MinIOAccessKey string `env:"SAKI_AGENT_MINIO_ACCESS_KEY"`
	MinIOSecretKey string `env:"SAKI_AGENT_MINIO_SECRET_KEY"`
	MinIOBucket    string `env:"SAKI_AGENT_MINIO_BUCKET"`
	MinIOPrefix    string `env:"SAKI_AGENT_MINIO_PREFIX" envDefault:"runtime-artifacts"`
	MinIOUseSSL    bool   `env:"SAKI_AGENT_MINIO_USE_SSL" envDefault:"false"`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, fmt.Errorf("解析环境变量失败: %w", err)
	}
	cfg.applyDefaults()
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c *Config) applyDefaults() {
	defaultRunDir, defaultCacheDir := defaultAgentDirs()
	if strings.TrimSpace(c.RunDir) == "" {
		c.RunDir = defaultRunDir
	}
	if strings.TrimSpace(c.CacheDir) == "" {
		c.CacheDir = defaultCacheDir
	}
	if strings.TrimSpace(c.KernelsDir) == "" {
		c.KernelsDir = defaultKernelsDir()
	}
}

func defaultAgentDirs() (runDir string, cacheDir string) {
	cwd, err := os.Getwd()
	if err == nil && strings.TrimSpace(cwd) != "" {
		base := filepath.Join(cwd, ".saki-agent")
		return filepath.Join(base, "run"), filepath.Join(base, "cache")
	}
	home, err := os.UserHomeDir()
	if err == nil && strings.TrimSpace(home) != "" {
		return filepath.Join(home, ".saki-agent", "run"), filepath.Join(home, ".saki-agent", "cache")
	}
	base := filepath.Join(os.TempDir(), "saki-agent")
	return filepath.Join(base, "run"), filepath.Join(base, "cache")
}

func defaultKernelsDir() string {
	cwd, err := os.Getwd()
	if err != nil || strings.TrimSpace(cwd) == "" {
		return ""
	}
	candidates := []string{
		filepath.Join(cwd, "saki-kernels", "kernels"),
		filepath.Join(cwd, "..", "saki-kernels", "kernels"),
	}
	for _, candidate := range candidates {
		info, statErr := os.Stat(candidate)
		if statErr != nil {
			continue
		}
		if info.IsDir() {
			return candidate
		}
	}
	return ""
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.RunDir) == "" {
		return fmt.Errorf("SAKI_AGENT_RUN_DIR 不能为空")
	}
	if strings.TrimSpace(c.CacheDir) == "" {
		return fmt.Errorf("SAKI_AGENT_CACHE_DIR 不能为空")
	}
	minioFilled := 0
	for _, value := range []string{
		c.MinIOEndpoint,
		c.MinIOAccessKey,
		c.MinIOSecretKey,
		c.MinIOBucket,
	} {
		if strings.TrimSpace(value) != "" {
			minioFilled++
		}
	}
	if minioFilled > 0 && minioFilled < 4 {
		return fmt.Errorf("MinIO 配置不完整：需同时设置 endpoint/access_key/secret_key/bucket")
	}
	if strings.TrimSpace(c.RuntimeControlTarget) == "" {
		return fmt.Errorf("RUNTIME_CONTROL_TARGET 不能为空")
	}
	if c.HeartbeatIntervalSec <= 0 {
		return fmt.Errorf("SAKI_AGENT_HEARTBEAT_INTERVAL_SEC 必须大于 0")
	}
	if c.ConnectTimeoutSec <= 0 {
		return fmt.Errorf("SAKI_AGENT_CONNECT_TIMEOUT_SEC 必须大于 0")
	}
	if c.ReconnectInitialBackoffSec <= 0 {
		return fmt.Errorf("SAKI_AGENT_RECONNECT_INITIAL_BACKOFF_SEC 必须大于 0")
	}
	if c.ReconnectMaxBackoffSec <= 0 {
		return fmt.Errorf("SAKI_AGENT_RECONNECT_MAX_BACKOFF_SEC 必须大于 0")
	}
	if c.ReconnectMaxBackoffSec < c.ReconnectInitialBackoffSec {
		return fmt.Errorf("SAKI_AGENT_RECONNECT_MAX_BACKOFF_SEC 必须大于等于初始 backoff")
	}
	return nil
}
