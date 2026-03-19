package config

import (
	"reflect"
	"testing"
	"time"
)

func TestLoadIncludesAgentRuntimeConfig(t *testing.T) {
	t.Setenv("RUNTIME_BASE_URL", "http://127.0.0.1:18081")
	t.Setenv("AGENT_CONTROL_BIND", "127.0.0.1:19081")
	t.Setenv("AGENT_ID", "agent-a")
	t.Setenv("AGENT_VERSION", "1.2.3")
	t.Setenv("AGENT_TRANSPORT_MODE", "direct")
	t.Setenv("AGENT_CONTROL_BASE_URL", "http://127.0.0.1:19081")
	t.Setenv("AGENT_MAX_CONCURRENCY", "4")
	t.Setenv("AGENT_HEARTBEAT_INTERVAL", "15s")
	t.Setenv("AGENT_WORKER_COMMAND_JSON", `["python","-m","demo.worker"]`)

	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.RuntimeBaseURL != "http://127.0.0.1:18081" {
		t.Fatalf("unexpected runtime base url: %q", cfg.RuntimeBaseURL)
	}
	if cfg.AgentControlBind != "127.0.0.1:19081" {
		t.Fatalf("unexpected agent control bind: %q", cfg.AgentControlBind)
	}
	if cfg.AgentID != "agent-a" {
		t.Fatalf("unexpected agent id: %q", cfg.AgentID)
	}
	if cfg.AgentVersion != "1.2.3" {
		t.Fatalf("unexpected agent version: %q", cfg.AgentVersion)
	}
	if cfg.AgentTransportMode != "direct" {
		t.Fatalf("unexpected agent transport mode: %q", cfg.AgentTransportMode)
	}
	if cfg.AgentControlBaseURL != "http://127.0.0.1:19081" {
		t.Fatalf("unexpected agent control base url: %q", cfg.AgentControlBaseURL)
	}
	if cfg.AgentMaxConcurrency != 4 {
		t.Fatalf("unexpected agent max concurrency: %d", cfg.AgentMaxConcurrency)
	}
	if cfg.AgentHeartbeatInterval != 15*time.Second {
		t.Fatalf("unexpected heartbeat interval: %s", cfg.AgentHeartbeatInterval)
	}
	if !reflect.DeepEqual(cfg.AgentWorkerCommand, []string{"python", "-m", "demo.worker"}) {
		t.Fatalf("unexpected worker command: %#v", cfg.AgentWorkerCommand)
	}
}
