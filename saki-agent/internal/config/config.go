package config

import (
	"fmt"

	"github.com/caarlos0/env/v11"
)

type Config struct {
	RunDir         string `env:"SAKI_AGENT_RUN_DIR" envDefault:"/var/run/saki-agent"`
	LogLevel       string `env:"LOG_LEVEL" envDefault:"info"`
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
	return cfg, nil
}
