package runtime

import (
	"context"
	"errors"
	"testing"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

func TestControlServerReturnsFailedPreconditionWhenAllSlotsBusy(t *testing.T) {
	service := NewService("agent-a", 2, &blockingLauncher{}, &memoryTaskEventPusher{})
	server := NewControlServer(service)

	first, err := server.AssignTask(context.Background(), connect.NewRequest(&runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
	}))
	if err != nil {
		t.Fatalf("assign first task: %v", err)
	}
	if !first.Msg.GetAccepted() {
		t.Fatalf("expected first assignment accepted, got %+v", first.Msg)
	}

	second, err := server.AssignTask(context.Background(), connect.NewRequest(&runtimev1.AssignTaskRequest{
		TaskId:      "task-2",
		ExecutionId: "exec-2",
		TaskType:    "predict",
	}))
	if err != nil {
		t.Fatalf("assign second task: %v", err)
	}
	if !second.Msg.GetAccepted() {
		t.Fatalf("expected second assignment accepted, got %+v", second.Msg)
	}

	_, err = server.AssignTask(context.Background(), connect.NewRequest(&runtimev1.AssignTaskRequest{
		TaskId:      "task-3",
		ExecutionId: "exec-3",
		TaskType:    "predict",
	}))
	if err == nil {
		t.Fatal("expected failed precondition error")
	}
	connectErr := new(connect.Error)
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected connect error, got %T", err)
	}
	if connectErr.Code() != connect.CodeFailedPrecondition {
		t.Fatalf("unexpected error code: %v", connectErr.Code())
	}

	if _, stopErr := server.StopTask(context.Background(), connect.NewRequest(&runtimev1.StopTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Reason:      "cancel_requested",
	})); stopErr != nil {
		t.Fatalf("stop first task: %v", stopErr)
	}
	if _, stopErr := server.StopTask(context.Background(), connect.NewRequest(&runtimev1.StopTaskRequest{
		TaskId:      "task-2",
		ExecutionId: "exec-2",
		Reason:      "cancel_requested",
	})); stopErr != nil {
		t.Fatalf("stop second task: %v", stopErr)
	}
}

type noOpLauncher struct{}

func (n *noOpLauncher) Execute(context.Context, *workerv1.ExecuteRequest, WorkerEventSink) (*workerv1.ExecuteResult, error) {
	return &workerv1.ExecuteResult{Ok: true}, nil
}
