package main

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"sync"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/elebirds/saki/saki-agent/internal/app/config"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
	"github.com/elebirds/saki/saki-agent/internal/plugins/launcher"
	"google.golang.org/protobuf/proto"
)

func TestNewRunnerWiresControlServerToWorkerAndRuntimeIngress(t *testing.T) {
	if len(os.Args) > 1 && os.Args[len(os.Args)-1] == "__main_worker_helper__" {
		runMainWorkerHelperProcess()
		return
	}

	runtimeServer := &recordingRuntimeIngressServer{}
	runtimeMux := http.NewServeMux()
	runtimePath, runtimeHandler := runtimev1connect.NewAgentIngressHandler(runtimeServer)
	runtimeMux.Handle(runtimePath, runtimeHandler)
	runtimeHTTPServer := httptest.NewServer(runtimeMux)
	defer runtimeHTTPServer.Close()

	runner := newRunner(config.Config{
		RuntimeBaseURL:         runtimeHTTPServer.URL,
		AgentControlBind:       "127.0.0.1:0",
		AgentTransportMode:     "pull",
		AgentID:                "agent-main-test",
		AgentVersion:           "test-version",
		AgentMaxConcurrency:    2,
		AgentHeartbeatInterval: 10 * time.Millisecond,
		AgentWorkerCommand:     mainHelperCommand(t),
	}, slog.New(slog.NewTextHandler(io.Discard, nil)))

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	backgroundDone := make(chan error, 1)
	go func() {
		backgroundDone <- runner.StartBackground(ctx)
	}()

	waitForCondition(t, time.Second, func() bool {
		return runtimeServer.registerCallCount() > 0 && runtimeServer.heartbeatCallCount() > 0
	}, "expected bootstrap register and heartbeat")
	if got := runtimeServer.firstRegister(); got == nil || got.GetTransportMode() != "pull" || got.GetMaxConcurrency() != 2 {
		t.Fatalf("unexpected register payload: %+v", got)
	}
	if got := runtimeServer.firstHeartbeat(); got == nil || got.GetMaxConcurrency() != 2 {
		t.Fatalf("unexpected heartbeat payload: %+v", got)
	}

	controlHTTPServer := httptest.NewServer(runner.Server().Handler)
	defer controlHTTPServer.Close()

	controlClient := runtimev1connect.NewAgentControlClient(http.DefaultClient, controlHTTPServer.URL)
	if _, err := controlClient.AssignTask(context.Background(), connect.NewRequest(&runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
		Payload:     []byte(`{"input":"demo"}`),
	})); err != nil {
		t.Fatalf("assign task: %v", err)
	}

	waitForCondition(t, 2*time.Second, func() bool {
		return runtimeServer.hasRunningHeartbeat("task-1") &&
			runtimeServer.hasPhase(runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING) &&
			runtimeServer.hasPhase(runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED) &&
			runtimeServer.hasProgress(42, "halfway") &&
			runtimeServer.hasResultPayload([]byte(`{"artifact":"best.pt"}`))
	}, "expected worker execution and runtime events to be wired")

	cancel()
	select {
	case err := <-backgroundDone:
		if err != nil {
			t.Fatalf("background exited with error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("background did not stop after cancel")
	}
}

func mainHelperCommand(t *testing.T) []string {
	t.Helper()

	return []string{
		os.Args[0],
		"-test.run=TestNewRunnerWiresControlServerToWorkerAndRuntimeIngress",
		"--",
		"__main_worker_helper__",
	}
}

func runMainWorkerHelperProcess() {
	req, err := launcher.ReadExecuteRequest(os.Stdin)
	if err != nil {
		panic(err)
	}

	if err := launcher.WriteWorkerEvent(os.Stdout, &workerv1.WorkerEvent{
		RequestId: req.GetRequestId(),
		TaskId:    req.GetTaskId(),
		EventType: "progress",
		Payload:   []byte(`{"percent":42,"message":"halfway"}`),
	}); err != nil {
		panic(err)
	}

	if err := launcher.WriteWorkerEvent(os.Stdout, &workerv1.WorkerEvent{
		RequestId: req.GetRequestId(),
		TaskId:    req.GetTaskId(),
		EventType: "result",
		Payload:   []byte(`{"artifact":"best.pt"}`),
	}); err != nil {
		panic(err)
	}

	time.Sleep(40 * time.Millisecond)

	if err := launcher.WriteExecuteResult(os.Stdout, &workerv1.ExecuteResult{
		RequestId: req.GetRequestId(),
		Ok:        true,
		Payload:   []byte(`{"ok":true}`),
	}); err != nil {
		panic(err)
	}
}

func waitForCondition(t *testing.T, timeout time.Duration, predicate func() bool, message string) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if predicate() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal(message)
}

type recordingRuntimeIngressServer struct {
	runtimev1connect.UnimplementedAgentIngressHandler

	mu         sync.Mutex
	registers  []*runtimev1.RegisterRequest
	heartbeats []*runtimev1.HeartbeatRequest
	events     []*runtimev1.TaskEventEnvelope
}

func (s *recordingRuntimeIngressServer) Register(_ context.Context, req *connect.Request[runtimev1.RegisterRequest]) (*connect.Response[runtimev1.RegisterResponse], error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.registers = append(s.registers, proto.Clone(req.Msg).(*runtimev1.RegisterRequest))
	return connect.NewResponse(&runtimev1.RegisterResponse{Accepted: true}), nil
}

func (s *recordingRuntimeIngressServer) Heartbeat(_ context.Context, req *connect.Request[runtimev1.HeartbeatRequest]) (*connect.Response[runtimev1.HeartbeatResponse], error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.heartbeats = append(s.heartbeats, proto.Clone(req.Msg).(*runtimev1.HeartbeatRequest))
	return connect.NewResponse(&runtimev1.HeartbeatResponse{Accepted: true}), nil
}

func (s *recordingRuntimeIngressServer) PushTaskEvent(_ context.Context, req *connect.Request[runtimev1.PushTaskEventRequest]) (*connect.Response[runtimev1.PushTaskEventResponse], error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.events = append(s.events, proto.Clone(req.Msg.GetEvent()).(*runtimev1.TaskEventEnvelope))
	return connect.NewResponse(&runtimev1.PushTaskEventResponse{Accepted: true}), nil
}

func (s *recordingRuntimeIngressServer) registerCallCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.registers)
}

func (s *recordingRuntimeIngressServer) heartbeatCallCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.heartbeats)
}

func (s *recordingRuntimeIngressServer) firstRegister() *runtimev1.RegisterRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.registers) == 0 {
		return nil
	}
	return s.registers[0]
}

func (s *recordingRuntimeIngressServer) firstHeartbeat() *runtimev1.HeartbeatRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.heartbeats) == 0 {
		return nil
	}
	return s.heartbeats[0]
}

func (s *recordingRuntimeIngressServer) hasRunningHeartbeat(taskID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, heartbeat := range s.heartbeats {
		if slices.Contains(heartbeat.GetRunningTaskIds(), taskID) {
			return true
		}
	}
	return false
}

func (s *recordingRuntimeIngressServer) hasPhase(phase runtimev1.TaskEventPhase) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, event := range s.events {
		if event.GetPhase() == phase {
			return true
		}
	}
	return false
}

func (s *recordingRuntimeIngressServer) hasProgress(percent int32, message string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, event := range s.events {
		progress := event.GetProgress()
		if progress != nil && progress.GetPercent() == percent && progress.GetMessage() == message {
			return true
		}
	}
	return false
}

func (s *recordingRuntimeIngressServer) hasResultPayload(payload []byte) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, event := range s.events {
		result := event.GetResult()
		if result != nil && slices.Equal(result.GetPayload(), payload) {
			return true
		}
	}
	return false
}
