package config

import "github.com/caarlos0/env/v11"

type Config struct {
	PublicAPIBind                string   `env:"PUBLIC_API_BIND" envDefault:":8080"`
	RuntimeBind                  string   `env:"RUNTIME_BIND" envDefault:":8081"`
	BuildVersion                 string   `env:"BUILD_VERSION" envDefault:"dev"`
	RuntimeRoles                 []string `env:"RUNTIME_ROLES" envDefault:"ingress,scheduler,delivery,recovery" envSeparator:","`
	RuntimeAssignAckTimeout      string   `env:"RUNTIME_ASSIGN_ACK_TIMEOUT" envDefault:"30s"`
	RuntimeAgentHeartbeatTimeout string   `env:"RUNTIME_AGENT_HEARTBEAT_TIMEOUT" envDefault:"30s"`
	LogLevel                     string   `env:"LOG_LEVEL" envDefault:"INFO"`
	LogFormat                    string   `env:"LOG_FORMAT" envDefault:"AUTO"`
	DatabaseDSN                  string   `env:"DATABASE_DSN"`
	AuthTokenSecret              string   `env:"AUTH_TOKEN_SECRET" envDefault:"dev-secret"`
	AuthTokenTTL                 string   `env:"AUTH_TOKEN_TTL" envDefault:"10m"`
	MinIOEndpoint                string   `env:"MINIO_ENDPOINT"`
	MinIOAccessKey               string   `env:"MINIO_ACCESS_KEY"`
	MinIOSecretKey               string   `env:"MINIO_SECRET_KEY"`
	MinIOBucketName              string   `env:"MINIO_BUCKET_NAME"`
	MinIOSecure                  bool     `env:"MINIO_SECURE" envDefault:"false"`
	AssetReadyRetentionWindow    string   `env:"ASSET_READY_RETENTION_WINDOW" envDefault:"24h"`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}
