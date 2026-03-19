package runtime

import (
	"context"
	"errors"
	"sync"

	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	workerv1 "github.com/elebirds/saki/saki-agent/internal/gen/worker/v1"
	"github.com/elebirds/saki/saki-agent/internal/app/reporting"
	taskrunner "github.com/elebirds/saki/saki-agent/internal/runtime/task_runner"
)

var errAgentBusy = errors.New("agent is busy")

type WorkerEventSink = reporting.EventSink
type TaskEventPusher = reporting.TaskEventPusher

type Service struct {
	agentID  string
	launcher taskrunner.WorkerLauncher
	pusher   TaskEventPusher

	mu      sync.Mutex
	current *activeExecution
}

type activeExecution struct {
	taskID      string
	executionID string
	cancel      context.CancelFunc
}

func NewService(agentID string, launcher taskrunner.WorkerLauncher, pusher TaskEventPusher) *Service {
	return &Service{
		agentID:  agentID,
		launcher: launcher,
		pusher:   pusher,
	}
}

func (s *Service) AssignTask(_ context.Context, req *runtimev1.AssignTaskRequest) error {
	if req == nil {
		return nil
	}

	s.mu.Lock()
	if s.current != nil {
		s.mu.Unlock()
		return errAgentBusy
	}
	execCtx, cancel := context.WithCancel(context.Background())
	current := &activeExecution{
		taskID:      req.GetTaskId(),
		executionID: req.GetExecutionId(),
		cancel:      cancel,
	}
	s.current = current
	s.mu.Unlock()

	go s.runExecution(execCtx, current, req)
	return nil
}

func (s *Service) StopTask(_ context.Context, req *runtimev1.StopTaskRequest) error {
	if req == nil {
		return nil
	}

	s.mu.Lock()
	current := s.current
	s.mu.Unlock()

	if current == nil {
		return nil
	}
	if current.taskID != req.GetTaskId() || current.executionID != req.GetExecutionId() {
		return nil
	}

	current.cancel()
	return nil
}

func (s *Service) RunningTaskIDs() []string {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.current == nil {
		return nil
	}
	return []string{s.current.taskID}
}

func (s *Service) runExecution(ctx context.Context, current *activeExecution, req *runtimev1.AssignTaskRequest) {
	defer s.clearCurrent(current)

	s.pushPhase(context.Background(), req.GetTaskId(), req.GetExecutionId(), runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING)

	runner := taskrunner.NewRunner(
		s.launcher,
		reporting.NewRuntimeSink(s.pusher, s.agentID, req.GetTaskId(), req.GetExecutionId()),
	)
	result, err := runner.Run(ctx, &workerv1.ExecuteRequest{
		RequestId: req.GetExecutionId(),
		TaskId:    req.GetTaskId(),
		Action:    req.GetTaskType(),
		Payload:   append([]byte(nil), req.GetPayload()...),
	})

	phase := runtimev1.TaskEventPhase_TASK_EVENT_PHASE_FAILED
	switch {
	case errors.Is(err, context.Canceled) || errors.Is(ctx.Err(), context.Canceled):
		phase = runtimev1.TaskEventPhase_TASK_EVENT_PHASE_CANCELED
	case err != nil:
		phase = runtimev1.TaskEventPhase_TASK_EVENT_PHASE_FAILED
	case result != nil && result.GetOk():
		phase = runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED
	default:
		phase = runtimev1.TaskEventPhase_TASK_EVENT_PHASE_FAILED
	}

	s.pushPhase(context.Background(), req.GetTaskId(), req.GetExecutionId(), phase)
}

func (s *Service) clearCurrent(current *activeExecution) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.current == current {
		s.current = nil
	}
}

func (s *Service) pushPhase(ctx context.Context, taskID, executionID string, phase runtimev1.TaskEventPhase) {
	if s.pusher == nil {
		return
	}
	_ = s.pusher.PushTaskEvent(ctx, &runtimev1.TaskEventEnvelope{
		AgentId:     s.agentID,
		TaskId:      taskID,
		ExecutionId: executionID,
		Phase:       phase,
	})
}
