package internalrpc

import (
	"context"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

const defaultHeartbeatInterval = 30 * time.Second

type registerAgentHandler interface {
	Handle(ctx context.Context, cmd commands.RegisterAgentCommand) (*commands.AgentRecord, error)
}

type heartbeatAgentHandler interface {
	Handle(ctx context.Context, cmd commands.HeartbeatAgentCommand) error
}

type startTaskHandler interface {
	Handle(ctx context.Context, cmd commands.StartTaskCommand) (*commands.TaskRecord, error)
}

type completeTaskHandler interface {
	Handle(ctx context.Context, cmd commands.CompleteTaskCommand) (*commands.TaskRecord, error)
}

type failTaskHandler interface {
	Handle(ctx context.Context, cmd commands.FailTaskCommand) (*commands.TaskRecord, error)
}

type confirmCanceledTaskHandler interface {
	Handle(ctx context.Context, cmd commands.ConfirmTaskCanceledCommand) (*commands.TaskRecord, error)
}

type RuntimeServer struct {
	runtimev1connect.UnimplementedAgentIngressHandler

	registers         registerAgentHandler
	heartbeats        heartbeatAgentHandler
	starts            startTaskHandler
	completes         completeTaskHandler
	fails             failTaskHandler
	confirmsCanceled  confirmCanceledTaskHandler
	heartbeatInterval time.Duration
}

func NewRuntimeServer(
	registers registerAgentHandler,
	heartbeats heartbeatAgentHandler,
	starts startTaskHandler,
	completes completeTaskHandler,
	fails failTaskHandler,
	confirmsCanceled confirmCanceledTaskHandler,
) *RuntimeServer {
	return &RuntimeServer{
		registers:         registers,
		heartbeats:        heartbeats,
		starts:            starts,
		completes:         completes,
		fails:             fails,
		confirmsCanceled:  confirmsCanceled,
		heartbeatInterval: defaultHeartbeatInterval,
	}
}

func (s *RuntimeServer) Register(
	ctx context.Context,
	req *connect.Request[runtimev1.RegisterRequest],
) (*connect.Response[runtimev1.RegisterResponse], error) {
	if _, err := s.registers.Handle(ctx, commands.RegisterAgentCommand{
		AgentID:      req.Msg.GetAgentId(),
		Version:      req.Msg.GetVersion(),
		Capabilities: append([]string(nil), req.Msg.GetCapabilities()...),
		SeenAt:       time.Now(),
	}); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&runtimev1.RegisterResponse{
		Accepted:            true,
		HeartbeatIntervalMs: s.heartbeatInterval.Milliseconds(),
	}), nil
}

func (s *RuntimeServer) Heartbeat(
	ctx context.Context,
	req *connect.Request[runtimev1.HeartbeatRequest],
) (*connect.Response[runtimev1.HeartbeatResponse], error) {
	seenAt := time.UnixMilli(req.Msg.GetSentAtUnixMs())
	if err := s.heartbeats.Handle(ctx, commands.HeartbeatAgentCommand{
		AgentID: req.Msg.GetAgentId(),
		SeenAt:  seenAt,
	}); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&runtimev1.HeartbeatResponse{
		Accepted:        true,
		NextHeartbeatMs: s.heartbeatInterval.Milliseconds(),
	}), nil
}

func (s *RuntimeServer) PushTaskEvent(
	ctx context.Context,
	req *connect.Request[runtimev1.PushTaskEventRequest],
) (*connect.Response[runtimev1.PushTaskEventResponse], error) {
	if err := s.IngestTaskEvent(ctx, req.Msg.GetEvent()); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&runtimev1.PushTaskEventResponse{
		Accepted: true,
	}), nil
}

func (s *RuntimeServer) IngestTaskEvent(ctx context.Context, envelope *runtimev1.TaskEventEnvelope) error {
	if envelope == nil {
		return nil
	}

	taskID, err := uuid.Parse(envelope.GetTaskId())
	if err != nil {
		return err
	}

	switch envelope.GetPhase() {
	case runtimev1.TaskEventPhase_TASK_EVENT_PHASE_RUNNING:
		_, err = s.starts.Handle(ctx, commands.StartTaskCommand{
			TaskID:      taskID,
			ExecutionID: envelope.GetExecutionId(),
		})
		return err
	case runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED:
		_, err = s.completes.Handle(ctx, commands.CompleteTaskCommand{
			TaskID:      taskID,
			ExecutionID: envelope.GetExecutionId(),
		})
		return err
	case runtimev1.TaskEventPhase_TASK_EVENT_PHASE_FAILED:
		_, err = s.fails.Handle(ctx, commands.FailTaskCommand{
			TaskID:      taskID,
			ExecutionID: envelope.GetExecutionId(),
		})
		return err
	case runtimev1.TaskEventPhase_TASK_EVENT_PHASE_CANCELED:
		_, err = s.confirmsCanceled.Handle(ctx, commands.ConfirmTaskCanceledCommand{
			TaskID:      taskID,
			ExecutionID: envelope.GetExecutionId(),
		})
		return err
	default:
		return nil
	}
}
