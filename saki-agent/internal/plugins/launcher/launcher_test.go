package launcher

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/elebirds/saki/saki-agent/internal/app/reporting"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

func TestLauncherExecutesEphemeralWorkerAndForwardsEvents(t *testing.T) {
	if os.Getenv("SAKI_AGENT_HELPER_PROCESS") == "1" {
		if os.Getenv("SAKI_AGENT_HELPER_MODE") == "block" {
			runBlockingWorkerHelperProcess()
			return
		}
		runWorkerHelperProcess()
		return
	}

	reporter := &reporting.MemorySink{}
	launcher := NewLauncher(LauncherConfig{
		Command: helperCommand(t),
		Env:     append(os.Environ(), "SAKI_AGENT_HELPER_PROCESS=1"),
		Timeout: 2 * time.Second,
	})

	result, err := launcher.Execute(context.Background(), &workerv1.ExecuteRequest{
		RequestId: "req-1",
		TaskId:    "task-1",
		Action:    "train",
		Payload:   []byte(`{"epochs":1}`),
	}, reporter)
	if err != nil {
		t.Fatalf("execute launcher: %v", err)
	}

	if result.GetRequestId() != "req-1" || !result.GetOk() {
		t.Fatalf("unexpected result: %+v", result)
	}
	if len(reporter.Events) != 1 {
		t.Fatalf("expected one worker event, got %+v", reporter.Events)
	}
	if reporter.Events[0].GetEventType() != "progress" {
		t.Fatalf("unexpected worker event: %+v", reporter.Events[0])
	}
}

func helperCommand(t *testing.T) []string {
	t.Helper()

	return []string{
		os.Args[0],
		"-test.run=TestLauncherExecutesEphemeralWorkerAndForwardsEvents",
		"--",
	}
}

func runWorkerHelperProcess() {
	req, err := ReadExecuteRequest(os.Stdin)
	if err != nil {
		panic(err)
	}

	if err := WriteWorkerEvent(os.Stdout, &workerv1.WorkerEvent{
		RequestId: req.GetRequestId(),
		TaskId:    req.GetTaskId(),
		EventType: "progress",
		Payload:   []byte(`{"percent":42}`),
	}); err != nil {
		panic(err)
	}

	if err := WriteExecuteResult(os.Stdout, &workerv1.ExecuteResult{
		RequestId: req.GetRequestId(),
		Ok:        true,
		Payload:   []byte(`{"artifact":"best.pt"}`),
	}); err != nil {
		panic(err)
	}
}

func runBlockingWorkerHelperProcess() {
	req, err := ReadExecuteRequest(os.Stdin)
	if err != nil {
		panic(err)
	}

	if err := WriteWorkerEvent(os.Stdout, &workerv1.WorkerEvent{
		RequestId: req.GetRequestId(),
		TaskId:    req.GetTaskId(),
		EventType: "progress",
		Payload:   []byte(`{"percent":1,"message":"started"}`),
	}); err != nil {
		panic(err)
	}

	select {}
}

func TestHelperProcess(_ *testing.T) {}
