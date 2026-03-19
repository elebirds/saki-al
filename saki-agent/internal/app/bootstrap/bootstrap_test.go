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

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
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

func TestBootstrapPullLoopConsumesCommandsAndAcksReceived(t *testing.T) {
	client := &fakeRuntimeClient{}
	delivery := &fakeDeliveryClient{
		commands: []*runtimev1.PulledCommand{
			{
				CommandId:     "cmd-1",
				CommandType:   "assign",
				TaskId:        "task-1",
				ExecutionId:   "exec-1",
				Payload:       []byte(`{"task_type":"predict"}`),
				DeliveryToken: "token-1",
			},
		},
	}
	handler := &fakePulledCommandHandler{}

	runner := New(Dependencies{
		Bind:              "127.0.0.1:0",
		RuntimeClient:     client,
		DeliveryClient:    delivery,
		CommandHandler:    handler,
		HeartbeatInterval: 10 * time.Millisecond,
		Logger:            slog.New(slog.NewTextHandler(io.Discard, nil)),
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- runner.StartBackground(ctx)
	}()

	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if handler.calls > 0 && delivery.ackCalls > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if handler.calls == 0 {
		t.Fatal("expected pull loop to hand command to local handler")
	}
	if delivery.ackCalls == 0 {
		t.Fatal("expected pull loop to ack received command")
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

type fakeDeliveryClient struct {
	commands  []*runtimev1.PulledCommand
	ackCalls  int
	commandID string
	token     string
}

func (f *fakeDeliveryClient) PullCommands(context.Context, int32, time.Duration) ([]*runtimev1.PulledCommand, error) {
	return append([]*runtimev1.PulledCommand(nil), f.commands...), nil
}

func (f *fakeDeliveryClient) AckReceived(_ context.Context, commandID, deliveryToken string) error {
	f.ackCalls++
	f.commandID = commandID
	f.token = deliveryToken
	return nil
}

type fakePulledCommandHandler struct {
	calls int
}

func (f *fakePulledCommandHandler) HandlePulledCommand(context.Context, *runtimev1.PulledCommand) error {
	f.calls++
	return nil
}
