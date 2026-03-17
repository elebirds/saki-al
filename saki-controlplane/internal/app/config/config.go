package config

import "github.com/caarlos0/env/v11"

type Config struct {
	PublicAPIBind               string `env:"PUBLIC_API_BIND" envDefault:":8080"`
	RuntimeBind                 string `env:"RUNTIME_BIND" envDefault:":8081"`
	RuntimeSchedulerTargetAgent string `env:"RUNTIME_SCHEDULER_TARGET_AGENT"`
	LogLevel                    string `env:"LOG_LEVEL" envDefault:"INFO"`
	LogFormat                   string `env:"LOG_FORMAT" envDefault:"AUTO"`
	DatabaseDSN                 string `env:"DATABASE_DSN"`
	AuthTokenSecret             string `env:"AUTH_TOKEN_SECRET" envDefault:"dev-secret"`
	AuthTokenTTL                string `env:"AUTH_TOKEN_TTL" envDefault:"24h"`
}

func Load() (Config, error) {
	cfg := Config{}
	if err := env.Parse(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}
