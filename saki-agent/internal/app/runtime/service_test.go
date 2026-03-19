package runtime

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
)

func TestServiceAssignTaskRunsWorkerAndPublishesRunningThenSucceeded(t *testing.T) {
	pusher := &memoryTaskEventPusher{}
	service := NewService("agent-a", &stubLauncher{
		result: &workerv1.ExecuteResult{
			RequestId: "exec-1",
			Ok:        true,
		},
	}, pusher)

	if err := service.AssignTask(context.Background(), &runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
		Payload:     []byte(`{"prompt":"hello"}`),
	}); err != nil {
		t.Fatalf("assign task: %v", err)
	}

	pusher.WaitForPhases(t, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED)
}

func TestServiceAssignTaskRejectsConcurrentAssignment(t *testing.T) {
	pusher := &memoryTaskEventPusher{}
	launcher := &blockingLauncher{}
	service := NewService("agent-a", launcher, pusher)

	if err := service.AssignTask(context.Background(), &runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
	}); err != nil {
		t.Fatalf("assign first task: %v", err)
	}

	err := service.AssignTask(context.Background(), &runtimev1.AssignTaskRequest{
		TaskId:      "task-2",
		ExecutionId: "exec-2",
		TaskType:    "predict",
	})
	if !errors.Is(err, errAgentBusy) {
		t.Fatalf("expected busy error, got %v", err)
	}

	if stopErr := service.StopTask(context.Background(), &runtimev1.StopTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Reason:      "cancel_requested",
	}); stopErr != nil {
		t.Fatalf("stop task: %v", stopErr)
	}
	pusher.WaitForPhases(t, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_CANCELED)
}

func TestServiceStopTaskCancelsMatchingExecutionAndPublishesCanceled(t *testing.T) {
	pusher := &memoryTaskEventPusher{}
	launcher := &blockingLauncher{}
	service := NewService("agent-a", launcher, pusher)

	if err := service.AssignTask(context.Background(), &runtimev1.AssignTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		TaskType:    "predict",
	}); err != nil {
		t.Fatalf("assign task: %v", err)
	}

	if err := service.StopTask(context.Background(), &runtimev1.StopTaskRequest{
		TaskId:      "task-1",
		ExecutionId: "exec-1",
		Reason:      "cancel_requested",
	}); err != nil {
		t.Fatalf("stop task: %v", err)
	}

	pusher.WaitForPhases(t, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING, runtimev1.TaskEventPhase_TASK_EVENT_PHASE_CANCELED)
}

type stubLauncher struct {
	result *workerv1.ExecuteResult
	err    error
}

func (s *stubLauncher) Execute(context.Context, *workerv1.ExecuteRequest, WorkerEventSink) (*workerv1.ExecuteResult, error) {
	return s.result, s.err
}

type blockingLauncher struct{}

func (b *blockingLauncher) Execute(ctx context.Context, _ *workerv1.ExecuteRequest, _ WorkerEventSink) (*workerv1.ExecuteResult, error) {
	<-ctx.Done()
	return nil, ctx.Err()
}

type memoryTaskEventPusher struct {
	mu      sync.Mutex
	events  []*runtimev1.TaskEventEnvelope
	waiters []chan struct{}
}

func (m *memoryTaskEventPusher) PushTaskEvent(_ context.Context, envelope *runtimev1.TaskEventEnvelope) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.events = append(m.events, envelope)
	for _, waiter := range m.waiters {
		close(waiter)
	}
	m.waiters = nil
	return nil
}

func (m *memoryTaskEventPusher) WaitForPhases(t *testing.T, phases ...runtimev1.TaskEventPhase) {
	t.Helper()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if m.hasPhases(phases...) {
			return
		}
		waiter := make(chan struct{})
		m.mu.Lock()
		m.waiters = append(m.waiters, waiter)
		m.mu.Unlock()
		select {
		case <-waiter:
		case <-time.After(20 * time.Millisecond):
		}
	}

	t.Fatalf("timed out waiting for phases: %+v, got %+v", phases, m.snapshotPhases())
}

func (m *memoryTaskEventPusher) hasPhases(phases ...runtimev1.TaskEventPhase) bool {
	m.mu.Lock()
	defer m.mu.Unlock()

	if len(m.events) < len(phases) {
		return false
	}
	for index, phase := range phases {
		if m.events[index].GetPhase() != phase {
			return false
		}
	}
	return true
}

func (m *memoryTaskEventPusher) snapshotPhases() []runtimev1.TaskEventPhase {
	m.mu.Lock()
	defer m.mu.Unlock()

	phases := make([]runtimev1.TaskEventPhase, 0, len(m.events))
	for _, event := range m.events {
		phases = append(phases, event.GetPhase())
	}
	return phases
}
