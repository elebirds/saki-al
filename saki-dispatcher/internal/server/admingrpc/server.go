package admingrpc

import (
	"context"
	"time"

	"github.com/rs/zerolog"

	"github.com/elebirds/saki/saki-dispatcher/internal/controlplane"
	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	dispatcheradminv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/dispatcheradminv1"
)

type Server struct {
	dispatcheradminv1.UnimplementedDispatcherAdminServer

	dispatcher *dispatch.Dispatcher
	commands   *controlplane.Service
	logger     zerolog.Logger
}

func NewServer(dispatcher *dispatch.Dispatcher, commands *controlplane.Service, logger zerolog.Logger) *Server {
	return &Server{
		dispatcher: dispatcher,
		commands:   commands,
		logger:     logger,
	}
}

func (s *Server) StartLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StartLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) PauseLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.PauseLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) ResumeLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.ResumeLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StopLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) ConfirmLoop(ctx context.Context, req *dispatcheradminv1.ConfirmLoopRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.ConfirmLoop(ctx, req.GetCommandId(), req.GetLoopId(), req.GetForce())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopJob(ctx context.Context, req *dispatcheradminv1.JobCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StopJob(ctx, req.GetCommandId(), req.GetJobId(), req.GetReason())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopTask(ctx context.Context, req *dispatcheradminv1.TaskCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StopTask(ctx, req.GetCommandId(), req.GetTaskId(), req.GetReason())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopRound(ctx context.Context, req *dispatcheradminv1.RoundCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StopRound(ctx, req.GetCommandId(), req.GetRoundId(), req.GetReason())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopStep(ctx context.Context, req *dispatcheradminv1.StepCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	result, err := s.commands.StopStep(ctx, req.GetCommandId(), req.GetStepId(), req.GetReason())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) TriggerDispatch(ctx context.Context, req *dispatcheradminv1.TriggerDispatchRequest) (*dispatcheradminv1.CommandResponse, error) {
	stepID := req.GetStepId()
	if stepID == "" {
		stepID = req.GetTaskId()
	}
	result, err := s.commands.TriggerDispatch(ctx, req.GetCommandId(), stepID)
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) GetRuntimeSummary(_ context.Context, _ *dispatcheradminv1.RuntimeSummaryRequest) (*dispatcheradminv1.RuntimeSummaryResponse, error) {
	snapshot := s.dispatcher.Summary()
	response := &dispatcheradminv1.RuntimeSummaryResponse{
		OnlineExecutors:    snapshot.OnlineExecutors,
		BusyExecutors:      snapshot.BusyExecutors,
		PendingAssignCount: snapshot.PendingAssign,
		PendingStopCount:   snapshot.PendingStop,
		QueuedTaskCount:    snapshot.QueuedTaskCount,
	}
	if !snapshot.LatestHeartbeatAt.IsZero() {
		response.LatestHeartbeatAt = snapshot.LatestHeartbeatAt.Format(time.RFC3339)
	}
	return response, nil
}

func (s *Server) GetExecutor(_ context.Context, req *dispatcheradminv1.ExecutorReadRequest) (*dispatcheradminv1.ExecutorReadResponse, error) {
	item, ok := s.dispatcher.GetExecutor(req.GetExecutorId())
	if !ok {
		return &dispatcheradminv1.ExecutorReadResponse{}, nil
	}
	return &dispatcheradminv1.ExecutorReadResponse{
		Item: convertExecutor(item),
	}, nil
}

func (s *Server) ListExecutors(_ context.Context, _ *dispatcheradminv1.ExecutorListRequest) (*dispatcheradminv1.ExecutorListResponse, error) {
	rows := s.dispatcher.ListExecutors()
	items := make([]*dispatcheradminv1.ExecutorRead, 0, len(rows))
	for _, item := range rows {
		items = append(items, convertExecutor(item))
	}
	return &dispatcheradminv1.ExecutorListResponse{Items: items}, nil
}

func convertCommandResult(result controlplane.CommandResult) *dispatcheradminv1.CommandResponse {
	return &dispatcheradminv1.CommandResponse{
		CommandId: result.CommandID,
		Status:    result.Status,
		Message:   result.Message,
		RequestId: result.RequestID,
	}
}

func convertExecutor(item dispatch.ExecutorSnapshot) *dispatcheradminv1.ExecutorRead {
	row := &dispatcheradminv1.ExecutorRead{
		ExecutorId:         item.ExecutorID,
		Version:            item.Version,
		Status:             item.Status,
		IsOnline:           item.IsOnline,
		CurrentTaskId:      item.CurrentTaskID,
		LastError:          item.LastError,
		PendingAssignCount: item.PendingAssign,
		PendingStopCount:   item.PendingStop,
	}
	if !item.LastSeen.IsZero() {
		row.LastSeenAt = item.LastSeen.Format(time.RFC3339)
	}
	return row
}
