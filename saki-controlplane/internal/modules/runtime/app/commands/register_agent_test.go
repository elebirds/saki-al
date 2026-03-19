package commands

import (
	"context"
	"testing"
	"time"
)

func TestRegisterAgentHandlerRequiresControlURLForDirectMode(t *testing.T) {
	registry := &fakeAgentRegistry{}
	handler := NewRegisterAgentHandler(registry)

	record, err := handler.Handle(context.Background(), RegisterAgentCommand{
		AgentID:        "agent-a",
		Version:        "1.2.3",
		TransportMode:  "direct",
		MaxConcurrency: 2,
	})
	if err == nil {
		t.Fatal("expected validation error for direct mode without control url")
	}
	if record != nil {
		t.Fatalf("expected nil record, got %+v", record)
	}
	if registry.registered != nil {
		t.Fatalf("expected registry not called, got %+v", registry.registered)
	}
}

func TestRegisterAgentHandlerNormalizesTransportAndConcurrency(t *testing.T) {
	registry := &fakeAgentRegistry{}
	handler := NewRegisterAgentHandler(registry)
	handler.now = func() time.Time { return time.UnixMilli(123456789) }

	record, err := handler.Handle(context.Background(), RegisterAgentCommand{
		AgentID:        "agent-a",
		Version:        "1.2.3",
		Capabilities:   []string{"gpu"},
		MaxConcurrency: 0,
	})
	if err != nil {
		t.Fatalf("handle register agent: %v", err)
	}

	if registry.registered == nil {
		t.Fatal("expected registry to be called")
	}
	if registry.registered.TransportMode != "pull" {
		t.Fatalf("expected default transport pull, got %+v", registry.registered)
	}
	if registry.registered.MaxConcurrency != 1 {
		t.Fatalf("expected normalized max concurrency 1, got %+v", registry.registered)
	}
	if !registry.registered.LastSeenAt.Equal(time.UnixMilli(123456789)) {
		t.Fatalf("unexpected last seen at: %s", registry.registered.LastSeenAt)
	}
	if record == nil || record.TransportMode != "pull" || record.MaxConcurrency != 1 {
		t.Fatalf("unexpected returned record: %+v", record)
	}
}
