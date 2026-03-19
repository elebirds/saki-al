package repo

import (
	"context"
	"testing"
	"time"
)

func TestAgentSessionRepoUpsertAndDelete(t *testing.T) {
	t.Setenv("TESTCONTAINERS_RYUK_DISABLED", "true")

	ctx := context.Background()
	pool, cleanup := openRuntimeTestPool(t, ctx)
	defer cleanup()

	agentRepo := NewAgentRepo(pool)
	if _, err := agentRepo.Upsert(ctx, UpsertAgentParams{
		ID:             "agent-relay-1",
		Version:        "1.0.0",
		TransportMode:  "relay",
		MaxConcurrency: 1,
		LastSeenAt:     time.UnixMilli(100),
	}); err != nil {
		t.Fatalf("upsert relay agent: %v", err)
	}

	sessionRepo := NewAgentSessionRepo(pool)
	connectedAt := time.UnixMilli(200)
	session, err := sessionRepo.Upsert(ctx, UpsertAgentSessionParams{
		AgentID:     "agent-relay-1",
		RelayID:     "http://relay.local",
		SessionID:   "session-1",
		ConnectedAt: connectedAt,
		LastSeenAt:  connectedAt,
	})
	if err != nil {
		t.Fatalf("upsert agent session: %v", err)
	}
	if session == nil || session.AgentID != "agent-relay-1" || session.SessionID != "session-1" {
		t.Fatalf("unexpected upserted session: %+v", session)
	}

	loaded, err := sessionRepo.GetByAgentID(ctx, "agent-relay-1")
	if err != nil {
		t.Fatalf("get agent session: %v", err)
	}
	if loaded == nil || loaded.RelayID != "http://relay.local" {
		t.Fatalf("unexpected loaded session: %+v", loaded)
	}

	if err := sessionRepo.Delete(ctx, "session-1"); err != nil {
		t.Fatalf("delete agent session: %v", err)
	}

	loaded, err = sessionRepo.GetByAgentID(ctx, "agent-relay-1")
	if err != nil {
		t.Fatalf("get deleted agent session: %v", err)
	}
	if loaded != nil {
		t.Fatalf("expected deleted session to disappear, got %+v", loaded)
	}
}
