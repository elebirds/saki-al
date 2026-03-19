package connect

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"
	"time"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

func TestRuntimeClientRegisterSendsAgentMetadata(t *testing.T) {
	server := &recordingAgentIngressServer{}
	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := NewRuntimeClient(http.DefaultClient, httpServer.URL, "agent-a", "1.2.3", "direct", "http://127.0.0.1:18081", 3, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := client.Register(context.Background(), []string{"gpu", "cuda"}); err != nil {
		t.Fatalf("register: %v", err)
	}

	if server.register == nil {
		t.Fatal("expected register request")
	}
	if server.register.GetAgentId() != "agent-a" || server.register.GetVersion() != "1.2.3" {
		t.Fatalf("unexpected register request: %+v", server.register)
	}
	if !slices.Equal(server.register.GetCapabilities(), []string{"gpu", "cuda"}) {
		t.Fatalf("unexpected capabilities: %+v", server.register.GetCapabilities())
	}
	if server.register.GetTransportMode() != "direct" || server.register.GetControlBaseUrl() != "http://127.0.0.1:18081" {
		t.Fatalf("unexpected transport payload: %+v", server.register)
	}
	if server.register.GetMaxConcurrency() != 3 {
		t.Fatalf("unexpected max concurrency: %d", server.register.GetMaxConcurrency())
	}
}

func TestRuntimeClientHeartbeatIncludesRunningTaskIDs(t *testing.T) {
	server := &recordingAgentIngressServer{}
	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentIngressHandler(server)
	mux.Handle(path, handler)
	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := NewRuntimeClient(http.DefaultClient, httpServer.URL, "agent-a", "1.2.4", "pull", "", 4, slog.New(slog.NewTextHandler(io.Discard, nil)))
	client.now = func() time.Time { return time.UnixMilli(123456789) }

	if err := client.Heartbeat(context.Background(), []string{"task-1", "task-2"}); err != nil {
		t.Fatalf("heartbeat: %v", err)
	}

	if server.heartbeat == nil {
		t.Fatal("expected heartbeat request")
	}
	if server.heartbeat.GetAgentId() != "agent-a" || server.heartbeat.GetAgentVersion() != "1.2.4" {
		t.Fatalf("unexpected heartbeat request: %+v", server.heartbeat)
	}
	if !slices.Equal(server.heartbeat.GetRunningTaskIds(), []string{"task-1", "task-2"}) {
		t.Fatalf("unexpected running task ids: %+v", server.heartbeat.GetRunningTaskIds())
	}
	if server.heartbeat.GetSentAtUnixMs() != 123456789 {
		t.Fatalf("unexpected heartbeat timestamp: %d", server.heartbeat.GetSentAtUnixMs())
	}
	if server.heartbeat.GetMaxConcurrency() != 4 {
		t.Fatalf("unexpected heartbeat max concurrency: %d", server.heartbeat.GetMaxConcurrency())
	}
}

type recordingAgentIngressServer struct {
	runtimev1connect.UnimplementedAgentIngressHandler

	register  *runtimev1.RegisterRequest
	heartbeat *runtimev1.HeartbeatRequest
}

func (s *recordingAgentIngressServer) Register(_ context.Context, req *connect.Request[runtimev1.RegisterRequest]) (*connect.Response[runtimev1.RegisterResponse], error) {
	s.register = req.Msg
	return connect.NewResponse(&runtimev1.RegisterResponse{
		Accepted:            true,
		HeartbeatIntervalMs: 30000,
	}), nil
}

func (s *recordingAgentIngressServer) Heartbeat(_ context.Context, req *connect.Request[runtimev1.HeartbeatRequest]) (*connect.Response[runtimev1.HeartbeatResponse], error) {
	s.heartbeat = req.Msg
	return connect.NewResponse(&runtimev1.HeartbeatResponse{
		Accepted:        true,
		NextHeartbeatMs: 30000,
	}), nil
}

func (s *recordingAgentIngressServer) PushTaskEvent(context.Context, *connect.Request[runtimev1.PushTaskEventRequest]) (*connect.Response[runtimev1.PushTaskEventResponse], error) {
	return connect.NewResponse(&runtimev1.PushTaskEventResponse{Accepted: true}), nil
}
