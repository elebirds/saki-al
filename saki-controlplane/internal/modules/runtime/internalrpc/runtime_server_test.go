package internalrpc

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"connectrpc.com/connect"

	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

func TestRuntimeServerRegisterTranslatesToCommand(t *testing.T) {
	registrar := &fakeRegisterExecutorHandler{
		result: &commands.ExecutorRecord{
			ID:         "executor-a",
			Version:    "1.2.3",
			LastSeenAt: time.UnixMilli(123456789),
		},
	}
	server := NewRuntimeServer(registrar, &fakeHeartbeatExecutorHandler{}, &fakeCompleteTaskHandler{})

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentControlHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentControlClient(http.DefaultClient, httpServer.URL)
	resp, err := client.Register(context.Background(), connect.NewRequest(&runtimev1.RegisterRequest{
		ExecutorId:   "executor-a",
		Version:      "1.2.3",
		Capabilities: []string{"gpu"},
	}))
	if err != nil {
		t.Fatalf("register executor: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.HeartbeatIntervalMs == 0 {
		t.Fatalf("unexpected register response: %+v", resp.Msg)
	}
	if registrar.last.ExecutorID != "executor-a" || registrar.last.Version != "1.2.3" {
		t.Fatalf("unexpected register command: %+v", registrar.last)
	}
}

func TestRuntimeServerHeartbeatTranslatesToCommand(t *testing.T) {
	heartbeats := &fakeHeartbeatExecutorHandler{}
	server := NewRuntimeServer(&fakeRegisterExecutorHandler{}, heartbeats, &fakeCompleteTaskHandler{})

	mux := http.NewServeMux()
	path, handler := runtimev1connect.NewAgentControlHandler(server)
	mux.Handle(path, handler)

	httpServer := httptest.NewServer(mux)
	defer httpServer.Close()

	client := runtimev1connect.NewAgentControlClient(http.DefaultClient, httpServer.URL)
	resp, err := client.Heartbeat(context.Background(), connect.NewRequest(&runtimev1.HeartbeatRequest{
		ExecutorId:   "executor-a",
		AgentVersion: "1.2.4",
		SentAtUnixMs: 123456789,
	}))
	if err != nil {
		t.Fatalf("heartbeat executor: %v", err)
	}

	if !resp.Msg.Accepted || resp.Msg.NextHeartbeatMs == 0 {
		t.Fatalf("unexpected heartbeat response: %+v", resp.Msg)
	}
	if heartbeats.last.ExecutorID != "executor-a" || heartbeats.last.SeenAt.UnixMilli() != 123456789 {
		t.Fatalf("unexpected heartbeat command: %+v", heartbeats.last)
	}
}

func TestRuntimeServerIngestSucceededTaskEventCompletesTask(t *testing.T) {
	completer := &fakeCompleteTaskHandler{}
	server := NewRuntimeServer(&fakeRegisterExecutorHandler{}, &fakeHeartbeatExecutorHandler{}, completer)

	if err := server.IngestTaskEvent(context.Background(), &runtimev1.TaskEventEnvelope{
		ExecutorId:  "executor-a",
		TaskId:      "550e8400-e29b-41d4-a716-446655440000",
		ExecutionId: "exec-1",
		Phase:       runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED,
	}); err != nil {
		t.Fatalf("ingest task event: %v", err)
	}

	if completer.last.TaskID.String() != "550e8400-e29b-41d4-a716-446655440000" {
		t.Fatalf("unexpected complete task command: %+v", completer.last)
	}
}

type fakeRegisterExecutorHandler struct {
	last   commands.RegisterExecutorCommand
	result *commands.ExecutorRecord
}

func (f *fakeRegisterExecutorHandler) Handle(_ context.Context, cmd commands.RegisterExecutorCommand) (*commands.ExecutorRecord, error) {
	f.last = cmd
	if f.result != nil {
		return f.result, nil
	}
	return &commands.ExecutorRecord{
		ID:         cmd.ExecutorID,
		Version:    cmd.Version,
		LastSeenAt: cmd.SeenAt,
	}, nil
}

type fakeHeartbeatExecutorHandler struct {
	last commands.HeartbeatExecutorCommand
}

func (f *fakeHeartbeatExecutorHandler) Handle(_ context.Context, cmd commands.HeartbeatExecutorCommand) error {
	f.last = cmd
	return nil
}

type fakeCompleteTaskHandler struct {
	last commands.CompleteTaskCommand
}

func (f *fakeCompleteTaskHandler) Handle(_ context.Context, cmd commands.CompleteTaskCommand) (*commands.TaskRecord, error) {
	f.last = cmd
	return &commands.TaskRecord{}, nil
}
