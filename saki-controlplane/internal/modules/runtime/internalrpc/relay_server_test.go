package internalrpc

import (
	"context"
	"crypto/tls"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"
)

func TestAgentRelayDispatchesCommandToConnectedAgent(t *testing.T) {
	store := &fakeAgentSessionStore{}
	server := NewRelayServer("http://relay.test", store)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentRelayHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(h2c.NewHandler(mux, &http2.Server{}))
	defer httpServer.Close()

	client := runtimev1connect.NewAgentRelayClient(newRelayH2CClient(), httpServer.URL)

	agentStream := client.Open(context.Background())
	if err := agentStream.Send(&runtimev1.RelayFrame{
		FrameKind: "agent_hello",
		AgentId:   "agent-relay-1",
	}); err != nil {
		t.Fatalf("send agent hello: %v", err)
	}

	welcome, err := agentStream.Receive()
	if err != nil {
		t.Fatalf("receive welcome: %v", err)
	}
	if welcome.GetFrameKind() != "agent_welcome" || !welcome.GetAccepted() {
		t.Fatalf("unexpected welcome frame: %+v", welcome)
	}
	if welcome.GetSessionId() == "" {
		t.Fatalf("expected relay welcome session_id, got %+v", welcome)
	}

	dispatchStream := client.Open(context.Background())
	if err := dispatchStream.Send(&runtimev1.RelayFrame{
		FrameKind:   "dispatch_command",
		AgentId:     "agent-relay-1",
		CommandId:   "cmd-1",
		CommandType: "assign",
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Payload:     []byte(`{"task_type":"predict"}`),
	}); err != nil {
		t.Fatalf("send dispatch frame: %v", err)
	}

	command, err := agentStream.Receive()
	if err != nil {
		t.Fatalf("receive relayed command: %v", err)
	}
	if command.GetFrameKind() != "command" || command.GetCommandId() != "cmd-1" {
		t.Fatalf("unexpected relayed command: %+v", command)
	}

	if err := agentStream.Send(&runtimev1.RelayFrame{
		FrameKind: "command_result",
		AgentId:   "agent-relay-1",
		CommandId: "cmd-1",
		Accepted:  true,
	}); err != nil {
		t.Fatalf("send command result: %v", err)
	}

	result, err := dispatchStream.Receive()
	if err != nil {
		t.Fatalf("receive dispatch result: %v", err)
	}
	if result.GetFrameKind() != "dispatch_result" || !result.GetAccepted() {
		t.Fatalf("unexpected dispatch result: %+v", result)
	}
}

func TestAgentRelayRejectsDispatchWithoutSession(t *testing.T) {
	store := &fakeAgentSessionStore{}
	server := NewRelayServer("http://relay.test", store)

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentRelayHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(h2c.NewHandler(mux, &http2.Server{}))
	defer httpServer.Close()

	client := runtimev1connect.NewAgentRelayClient(newRelayH2CClient(), httpServer.URL)
	dispatchStream := client.Open(context.Background())
	if err := dispatchStream.Send(&runtimev1.RelayFrame{
		FrameKind:   "dispatch_command",
		AgentId:     "missing-agent",
		CommandId:   "cmd-missing",
		CommandType: "cancel",
		TaskId:      "task-2",
		ExecutionId: "exec-2",
	}); err != nil {
		t.Fatalf("send missing dispatch frame: %v", err)
	}

	result, err := dispatchStream.Receive()
	if err != nil {
		t.Fatalf("receive missing dispatch result: %v", err)
	}
	if result.GetAccepted() || result.GetFrameKind() != "dispatch_result" {
		t.Fatalf("expected rejected dispatch result, got %+v", result)
	}
	if result.GetErrorMessage() == "" {
		t.Fatalf("expected rejection reason, got %+v", result)
	}
}

type fakeAgentSessionStore struct {
	upserted []*runtimerepo.AgentSession
	deleted  []string
}

func (f *fakeAgentSessionStore) Upsert(_ context.Context, session runtimerepo.UpsertAgentSessionParams) (*runtimerepo.AgentSession, error) {
	copied := &runtimerepo.AgentSession{
		AgentID:     session.AgentID,
		RelayID:     session.RelayID,
		SessionID:   session.SessionID,
		ConnectedAt: session.ConnectedAt,
		LastSeenAt:  session.LastSeenAt,
	}
	f.upserted = append(f.upserted, copied)
	return copied, nil
}

func (f *fakeAgentSessionStore) Delete(_ context.Context, sessionID string) error {
	f.deleted = append(f.deleted, sessionID)
	return nil
}

func (f *fakeAgentSessionStore) Touch(_ context.Context, sessionID string, seenAt time.Time) error {
	for _, item := range f.upserted {
		if item.SessionID == sessionID {
			item.LastSeenAt = seenAt
		}
	}
	return nil
}

func (f *fakeAgentSessionStore) GetByAgentID(_ context.Context, agentID string) (*runtimerepo.AgentSession, error) {
	for _, item := range f.upserted {
		if item.AgentID == agentID {
			copied := *item
			return &copied, nil
		}
	}
	return nil, nil
}

func newRelayH2CClient() *http.Client {
	return &http.Client{
		Transport: &http2.Transport{
			AllowHTTP: true,
			DialTLSContext: func(ctx context.Context, network, addr string, _ *tls.Config) (net.Conn, error) {
				var d net.Dialer
				return d.DialContext(ctx, network, addr)
			},
		},
	}
}
