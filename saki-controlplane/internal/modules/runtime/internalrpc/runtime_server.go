package internalrpc

import (
	"context"
	"errors"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

const defaultHeartbeatInterval = 30 * time.Second

type registerExecutorHandler interface {
	Handle(ctx context.Context, cmd commands.RegisterExecutorCommand) (*commands.ExecutorRecord, error)
}

type heartbeatExecutorHandler interface {
	Handle(ctx context.Context, cmd commands.HeartbeatExecutorCommand) error
}

type completeTaskHandler interface {
	Handle(ctx context.Context, cmd commands.CompleteTaskCommand) (*commands.TaskRecord, error)
}

type RuntimeServer struct {
	runtimev1connect.UnimplementedAgentControlHandler

	registers         registerExecutorHandler
	heartbeats        heartbeatExecutorHandler
	completes         completeTaskHandler
	heartbeatInterval time.Duration
}

func NewRuntimeServer(
	registers registerExecutorHandler,
	heartbeats heartbeatExecutorHandler,
	completes completeTaskHandler,
) *RuntimeServer {
	return &RuntimeServer{
		registers:         registers,
		heartbeats:        heartbeats,
		completes:         completes,
		heartbeatInterval: defaultHeartbeatInterval,
	}
}

func (s *RuntimeServer) Register(
	ctx context.Context,
	req *connect.Request[runtimev1.RegisterRequest],
) (*connect.Response[runtimev1.RegisterResponse], error) {
	if _, err := s.registers.Handle(ctx, commands.RegisterExecutorCommand{
		ExecutorID:   req.Msg.GetExecutorId(),
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
	if err := s.heartbeats.Handle(ctx, commands.HeartbeatExecutorCommand{
		ExecutorID: req.Msg.GetExecutorId(),
		SeenAt:     seenAt,
	}); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&runtimev1.HeartbeatResponse{
		Accepted:        true,
		NextHeartbeatMs: s.heartbeatInterval.Milliseconds(),
	}), nil
}

func (s *RuntimeServer) AssignTask(
	context.Context,
	*connect.Request[runtimev1.AssignTaskRequest],
) (*connect.Response[runtimev1.AssignTaskResponse], error) {
	return nil, connect.NewError(connect.CodeUnimplemented, errors.New("assign task is agent-side RPC"))
}

func (s *RuntimeServer) StopTask(
	context.Context,
	*connect.Request[runtimev1.StopTaskRequest],
) (*connect.Response[runtimev1.StopTaskResponse], error) {
	return nil, connect.NewError(connect.CodeUnimplemented, errors.New("stop task is agent-side RPC"))
}

func (s *RuntimeServer) IngestTaskEvent(ctx context.Context, envelope *runtimev1.TaskEventEnvelope) error {
	if envelope == nil {
		return nil
	}

	switch envelope.GetPhase() {
	case runtimev1.TaskEventPhase_TASK_EVENT_PHASE_SUCCEEDED:
		taskID, err := uuid.Parse(envelope.GetTaskId())
		if err != nil {
			return err
		}
		_, err = s.completes.Handle(ctx, commands.CompleteTaskCommand{TaskID: taskID})
		return err
	default:
		return nil
	}
}
