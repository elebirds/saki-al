package config

import "testing"

func TestLoadConfigDefaults(t *testing.T) {
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.PublicAPIBind == "" || cfg.RuntimeBind == "" {
		t.Fatal("default binds must be set")
	}
}

func TestLoadConfigReadsBootstrapDependencies(t *testing.T) {
	t.Setenv("DATABASE_DSN", "postgres://postgres:postgres@localhost:5432/saki?sslmode=disable")
	t.Setenv("AUTH_TOKEN_SECRET", "test-secret")
	t.Setenv("AUTH_TOKEN_TTL", "45m")

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.DatabaseDSN != "postgres://postgres:postgres@localhost:5432/saki?sslmode=disable" {
		t.Fatalf("unexpected database dsn: %q", cfg.DatabaseDSN)
	}
	if cfg.AuthTokenSecret != "test-secret" {
		t.Fatalf("unexpected auth token secret: %q", cfg.AuthTokenSecret)
	}
	if cfg.AuthTokenTTL != "45m" {
		t.Fatalf("unexpected auth token ttl: %q", cfg.AuthTokenTTL)
	}
}
