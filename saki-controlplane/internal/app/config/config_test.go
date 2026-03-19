package config

import (
	"slices"
	"testing"
)

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

func TestLoadConfigReadsAccessBootstrapPrincipals(t *testing.T) {
	t.Setenv("AUTH_BOOTSTRAP_PRINCIPALS", `[{"user_id":"seed-user","display_name":"Seed User","permissions":["projects:read","imports:read"]}]`)

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(cfg.AuthBootstrapPrincipals) != 1 {
		t.Fatalf("expected one bootstrap principal, got %+v", cfg.AuthBootstrapPrincipals)
	}

	principal := cfg.AuthBootstrapPrincipals[0]
	if principal.UserID != "seed-user" {
		t.Fatalf("unexpected bootstrap user id: %+v", principal)
	}
	if principal.DisplayName != "Seed User" {
		t.Fatalf("unexpected bootstrap display name: %+v", principal)
	}
	if !slices.Equal(principal.Permissions, []string{"projects:read", "imports:read"}) {
		t.Fatalf("unexpected bootstrap permissions: %+v", principal)
	}
}

func TestLoadIncludesObjectStorageConfig(t *testing.T) {
	t.Setenv("MINIO_ENDPOINT", "127.0.0.1:9000")
	t.Setenv("MINIO_ACCESS_KEY", "test-access")
	t.Setenv("MINIO_SECRET_KEY", "test-secret")
	t.Setenv("MINIO_BUCKET_NAME", "assets")
	t.Setenv("MINIO_SECURE", "true")

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}

	if cfg.MinIOEndpoint != "127.0.0.1:9000" {
		t.Fatalf("unexpected object storage endpoint: %q", cfg.MinIOEndpoint)
	}
	if cfg.MinIOAccessKey != "test-access" {
		t.Fatalf("unexpected object storage access key: %q", cfg.MinIOAccessKey)
	}
	if cfg.MinIOSecretKey != "test-secret" {
		t.Fatalf("unexpected object storage secret key: %q", cfg.MinIOSecretKey)
	}
	if cfg.MinIOBucketName != "assets" {
		t.Fatalf("unexpected object storage bucket: %q", cfg.MinIOBucketName)
	}
	if !cfg.MinIOSecure {
		t.Fatal("expected object storage secure to be true")
	}
}

func TestLoadIncludesRuntimeAgentControlBaseURL(t *testing.T) {
	t.Setenv("RUNTIME_AGENT_CONTROL_BASE_URL", "http://127.0.0.1:18081")

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.RuntimeAgentControlBaseURL != "http://127.0.0.1:18081" {
		t.Fatalf("unexpected runtime agent control base url: %q", cfg.RuntimeAgentControlBaseURL)
	}
}
