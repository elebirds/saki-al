package config

import (
	"bytes"
	"encoding/json"

	"github.com/caarlos0/env/v11"
)

type BootstrapPrincipal struct {
	UserID      string   `json:"user_id"`
	DisplayName string   `json:"display_name"`
	Permissions []string `json:"permissions"`
}

type BootstrapPrincipals []BootstrapPrincipal

func (p *BootstrapPrincipals) UnmarshalText(text []byte) error {
	if len(bytes.TrimSpace(text)) == 0 {
		*p = nil
		return nil
	}

	var principals []BootstrapPrincipal
	if err := json.Unmarshal(text, &principals); err != nil {
		return err
	}

	*p = principals
	return nil
}

type Config struct {
	PublicAPIBind               string              `env:"PUBLIC_API_BIND" envDefault:":8080"`
	RuntimeBind                 string              `env:"RUNTIME_BIND" envDefault:":8081"`
	RuntimeSchedulerTargetAgent string              `env:"RUNTIME_SCHEDULER_TARGET_AGENT"`
	RuntimeAgentControlBaseURL  string              `env:"RUNTIME_AGENT_CONTROL_BASE_URL"`
	LogLevel                    string              `env:"LOG_LEVEL" envDefault:"INFO"`
	LogFormat                   string              `env:"LOG_FORMAT" envDefault:"AUTO"`
	DatabaseDSN                 string              `env:"DATABASE_DSN"`
	AuthTokenSecret             string              `env:"AUTH_TOKEN_SECRET" envDefault:"dev-secret"`
	AuthTokenTTL                string              `env:"AUTH_TOKEN_TTL" envDefault:"24h"`
	AuthBootstrapPrincipals     BootstrapPrincipals `env:"AUTH_BOOTSTRAP_PRINCIPALS"`
	MinIOEndpoint               string              `env:"MINIO_ENDPOINT"`
	MinIOAccessKey              string              `env:"MINIO_ACCESS_KEY"`
	MinIOSecretKey              string              `env:"MINIO_SECRET_KEY"`
	MinIOBucketName             string              `env:"MINIO_BUCKET_NAME"`
	MinIOSecure                 bool                `env:"MINIO_SECURE" envDefault:"false"`
	AssetReadyRetentionWindow   string              `env:"ASSET_READY_RETENTION_WINDOW" envDefault:"24h"`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}
