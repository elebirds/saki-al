package bootstrap

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

func TestBootstrapStartsAgentControlHTTPServerAndBackgroundLoops(t *testing.T) {
	var controlCalls int
	client := &fakeRuntimeClient{}
	source := &fakeRunningTaskSource{running: []string{"task-1"}}

	runner := New(Dependencies{
		Bind: "127.0.0.1:0",
		RuntimeClient: client,
		TaskSource:    source,
		Capabilities:  []string{"gpu"},
		HeartbeatInterval: 10 * time.Millisecond,
		ControlPath: "/saki.runtime.v1.AgentControl/",
		ControlHandler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			controlCalls++
			w.WriteHeader(http.StatusAccepted)
		}),
		Logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- runner.StartBackground(ctx)
	}()

	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if client.registerCalls > 0 && client.heartbeatCalls > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if client.registerCalls == 0 {
		t.Fatal("expected bootstrap to register agent")
	}
	if client.heartbeatCalls == 0 {
		t.Fatal("expected bootstrap to send heartbeat")
	}

	req := httptest.NewRequest(http.MethodPost, "/saki.runtime.v1.AgentControl/AssignTask", nil)
	resp := httptest.NewRecorder()
	runner.Server().Handler.ServeHTTP(resp, req)
	if controlCalls != 1 {
		t.Fatalf("expected control handler to be mounted once, got %d", controlCalls)
	}
	if resp.Code != http.StatusAccepted {
		t.Fatalf("unexpected control handler status: %d", resp.Code)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("background loops exited with error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("background loops did not stop after cancel")
	}
}

type fakeRuntimeClient struct {
	mu             sync.Mutex
	registerCalls  int
	heartbeatCalls int
}

func (f *fakeRuntimeClient) Register(context.Context, []string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.registerCalls++
	return nil
}

func (f *fakeRuntimeClient) Heartbeat(context.Context, []string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.heartbeatCalls++
	return nil
}

type fakeRunningTaskSource struct {
	running []string
}

func (f *fakeRunningTaskSource) RunningTaskIDs() []string {
	return append([]string(nil), f.running...)
}
