package task_runner

import (
	"context"
	"testing"

	"github.com/elebirds/saki/saki-agent/internal/app/reporting"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

func TestRunnerDelegatesToLauncher(t *testing.T) {
	reporter := &reporting.MemorySink{}
	launcher := &fakeLauncher{
		result: &workerv1.ExecuteResult{
			RequestId: "req-1",
			Ok:        true,
		},
	}

	runner := NewRunner(launcher, reporter)
	result, err := runner.Run(context.Background(), &workerv1.ExecuteRequest{
		RequestId: "req-1",
		TaskId:    "task-1",
		Action:    "train",
	})
	if err != nil {
		t.Fatalf("run task: %v", err)
	}
	if result.GetRequestId() != "req-1" {
		t.Fatalf("unexpected result: %+v", result)
	}
	if launcher.calls != 1 {
		t.Fatalf("expected launcher to be called once, got %d", launcher.calls)
	}
}

type fakeLauncher struct {
	calls  int
	result *workerv1.ExecuteResult
}

func (f *fakeLauncher) Execute(context.Context, *workerv1.ExecuteRequest, reporting.EventSink) (*workerv1.ExecuteResult, error) {
	f.calls++
	return f.result, nil
}
