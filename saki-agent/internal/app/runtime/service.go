package runtime

import (
	"context"
	"errors"

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
	slots    *SlotManager
}

type activeExecution struct {
	taskID      string
	executionID string
	cancel      context.CancelFunc
}

func NewService(agentID string, maxConcurrency int, launcher taskrunner.WorkerLauncher, pusher TaskEventPusher) *Service {
	return &Service{
		agentID:  agentID,
		launcher: launcher,
		pusher:   pusher,
		slots:    NewSlotManager(maxConcurrency),
	}
}

func (s *Service) AssignTask(_ context.Context, req *runtimev1.AssignTaskRequest) error {
	if req == nil {
		return nil
	}

	execCtx, cancel := context.WithCancel(context.Background())
	current := &activeExecution{
		taskID:      req.GetTaskId(),
		executionID: req.GetExecutionId(),
		cancel:      cancel,
	}
	if err := s.slotManager().Admit(current); err != nil {
		cancel()
		return err
	}

	go s.runExecution(execCtx, current, req)
	return nil
}

func (s *Service) StopTask(_ context.Context, req *runtimev1.StopTaskRequest) error {
	if req == nil {
		return nil
	}

	s.slotManager().Cancel(req.GetTaskId(), req.GetExecutionId())
	return nil
}

func (s *Service) RunningTaskIDs() []string {
	return s.slotManager().RunningTaskIDs()
}

func (s *Service) runExecution(ctx context.Context, current *activeExecution, req *runtimev1.AssignTaskRequest) {
	defer s.slotManager().Release(current.executionID)

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

func (s *Service) slotManager() *SlotManager {
	if s == nil || s.slots == nil {
		return NewSlotManager(1)
	}
	return s.slots
}

func normalizeServiceMaxConcurrency(limit int) int {
	if limit <= 0 {
		return 1
	}
	return limit
}
