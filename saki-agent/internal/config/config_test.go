package config

import "testing"

func TestApplyDefaultsUsesResolvedDirs(t *testing.T) {
	expectedRunDir, expectedCacheDir := defaultAgentDirs()
	cfg := Config{}
	cfg.applyDefaults()
	if cfg.RunDir != expectedRunDir {
		t.Fatalf("unexpected run dir: got=%s want=%s", cfg.RunDir, expectedRunDir)
	}
	if cfg.CacheDir != expectedCacheDir {
		t.Fatalf("unexpected cache dir: got=%s want=%s", cfg.CacheDir, expectedCacheDir)
	}
}

func TestValidateRequiresRunAndCacheDir(t *testing.T) {
	cfg := Config{
		RunDir:                     "",
		CacheDir:                   "/tmp/cache",
		RuntimeControlTarget:       "127.0.0.1:50051",
		HeartbeatIntervalSec:       10,
		ConnectTimeoutSec:          5,
		ReconnectInitialBackoffSec: 2,
		ReconnectMaxBackoffSec:     30,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected run dir validation error")
	}

	cfg = Config{
		RunDir:                     "/tmp/run",
		CacheDir:                   "",
		RuntimeControlTarget:       "127.0.0.1:50051",
		HeartbeatIntervalSec:       10,
		ConnectTimeoutSec:          5,
		ReconnectInitialBackoffSec: 2,
		ReconnectMaxBackoffSec:     30,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected cache dir validation error")
	}
}

func TestValidateMinIORequiresAllFields(t *testing.T) {
	cfg := Config{
		RunDir:                     "/tmp/run",
		CacheDir:                   "/tmp/cache",
		RuntimeControlTarget:       "127.0.0.1:50051",
		HeartbeatIntervalSec:       10,
		ConnectTimeoutSec:          5,
		ReconnectInitialBackoffSec: 2,
		ReconnectMaxBackoffSec:     30,
		MinIOEndpoint:              "127.0.0.1:9000",
	}
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected minio validation error")
	}

	cfg = Config{
		RunDir:                     "/tmp/run",
		CacheDir:                   "/tmp/cache",
		RuntimeControlTarget:       "127.0.0.1:50051",
		HeartbeatIntervalSec:       10,
		ConnectTimeoutSec:          5,
		ReconnectInitialBackoffSec: 2,
		ReconnectMaxBackoffSec:     30,
		MinIOEndpoint:              "127.0.0.1:9000",
		MinIOAccessKey:             "ak",
		MinIOSecretKey:             "sk",
		MinIOBucket:                "bucket",
	}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestValidateRuntimeControlBounds(t *testing.T) {
	cfg := Config{
		RunDir:                     "/tmp/run",
		CacheDir:                   "/tmp/cache",
		RuntimeControlTarget:       "",
		HeartbeatIntervalSec:       10,
		ConnectTimeoutSec:          5,
		ReconnectInitialBackoffSec: 2,
		ReconnectMaxBackoffSec:     30,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected runtime target validation error")
	}

	cfg.RuntimeControlTarget = "127.0.0.1:50051"
	cfg.HeartbeatIntervalSec = 0
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected heartbeat validation error")
	}

	cfg.HeartbeatIntervalSec = 10
	cfg.ReconnectInitialBackoffSec = 10
	cfg.ReconnectMaxBackoffSec = 2
	if err := cfg.Validate(); err == nil {
		t.Fatalf("expected backoff range validation error")
	}
}
