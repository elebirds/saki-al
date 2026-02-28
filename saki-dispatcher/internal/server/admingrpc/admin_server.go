package admingrpc

import (
	"context"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/elebirds/saki/saki-dispatcher/internal/controlplane"
	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	dispatcheradminv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/dispatcheradminv1"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

type Server struct {
	dispatcheradminv1.UnimplementedDispatcherAdminServer

	dispatcher *dispatch.Dispatcher
	commands   *controlplane.Service
	domain     *runtime_domain_client.Client
	logger     zerolog.Logger
}

func NewServer(
	dispatcher *dispatch.Dispatcher,
	commands *controlplane.Service,
	domain *runtime_domain_client.Client,
	logger zerolog.Logger,
) *Server {
	return &Server{
		dispatcher: dispatcher,
		commands:   commands,
		domain:     domain,
		logger:     logger,
	}
}

func (s *Server) StartLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetLoopId(), "loop_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.StartLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) PauseLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetLoopId(), "loop_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.PauseLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) ResumeLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetLoopId(), "loop_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.ResumeLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopLoop(ctx context.Context, req *dispatcheradminv1.LoopCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetLoopId(), "loop_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.StopLoop(ctx, req.GetCommandId(), req.GetLoopId())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) ConfirmLoop(ctx context.Context, req *dispatcheradminv1.ConfirmLoopRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetLoopId(), "loop_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.ConfirmLoop(ctx, req.GetCommandId(), req.GetLoopId(), req.GetForce())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopRound(ctx context.Context, req *dispatcheradminv1.RoundCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetRoundId(), "round_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.StopRound(ctx, req.GetCommandId(), req.GetRoundId(), req.GetReason())
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) RetryRound(ctx context.Context, req *dispatcheradminv1.RetryRoundRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetRoundId(), "round_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.RetryRound(
		ctx,
		req.GetCommandId(),
		req.GetRoundId(),
		req.GetReason(),
	)
	if err != nil {
		return nil, err
	}
	return convertCommandResult(result), nil
}

func (s *Server) StopStep(ctx context.Context, req *dispatcheradminv1.StepCommandRequest) (*dispatcheradminv1.CommandResponse, error) {
	if err := validateUUIDField(req.GetStepId(), "step_id"); err != nil {
		return nil, err
	}
	result, err := s.commands.StopStep(ctx, req.GetCommandId(), req.GetStepId(), req.GetReason())
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
		QueuedStepCount:    snapshot.QueuedStepCount,
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

func (s *Server) GetRuntimeDomainStatus(
	_ context.Context,
	_ *dispatcheradminv1.RuntimeDomainStatusRequest,
) (*dispatcheradminv1.RuntimeDomainStatusResponse, error) {
	if s.domain == nil {
		return &dispatcheradminv1.RuntimeDomainStatusResponse{
			Configured: false,
			Enabled:    false,
			State:      runtime_domain_client.StateDisabled,
			LastError:  "runtime_domain 客户端不可用",
		}, nil
	}
	statusSnapshot := s.domain.Status()
	response := &dispatcheradminv1.RuntimeDomainStatusResponse{
		Configured:          statusSnapshot.Configured,
		Enabled:             statusSnapshot.Enabled,
		State:               statusSnapshot.State,
		Target:              statusSnapshot.Target,
		ConsecutiveFailures: statusSnapshot.ConsecutiveFailures,
		LastError:           statusSnapshot.LastError,
	}
	if !statusSnapshot.LastConnectedAt.IsZero() {
		response.LastConnectedAt = statusSnapshot.LastConnectedAt.Format(time.RFC3339)
	}
	if !statusSnapshot.NextRetryAt.IsZero() {
		response.NextRetryAt = statusSnapshot.NextRetryAt.Format(time.RFC3339)
	}
	return response, nil
}

func (s *Server) SetRuntimeDomainEnabled(
	_ context.Context,
	req *dispatcheradminv1.SetRuntimeDomainEnabledRequest,
) (*dispatcheradminv1.CommandResponse, error) {
	commandID := normalizeCommandID(req.GetCommandId())
	if s.domain == nil {
		return buildRuntimeDomainCommandResponse(commandID, "failed", "runtime_domain 客户端不可用"), nil
	}
	if req.GetEnabled() {
		if err := s.domain.Enable(); err != nil {
			return buildRuntimeDomainCommandResponse(commandID, "failed", err.Error()), nil
		}
		return buildRuntimeDomainCommandResponse(commandID, "applied", "runtime_domain 已启用"), nil
	}
	if err := s.domain.Disable(); err != nil {
		return buildRuntimeDomainCommandResponse(commandID, "failed", err.Error()), nil
	}
	return buildRuntimeDomainCommandResponse(commandID, "applied", "runtime_domain 已停用"), nil
}

func (s *Server) ReconnectRuntimeDomain(
	_ context.Context,
	req *dispatcheradminv1.ReconnectRuntimeDomainRequest,
) (*dispatcheradminv1.CommandResponse, error) {
	commandID := normalizeCommandID(req.GetCommandId())
	if s.domain == nil {
		return buildRuntimeDomainCommandResponse(commandID, "failed", "runtime_domain 客户端不可用"), nil
	}
	if err := s.domain.Reconnect(); err != nil {
		return buildRuntimeDomainCommandResponse(commandID, "failed", err.Error()), nil
	}
	return buildRuntimeDomainCommandResponse(commandID, "applied", "runtime_domain 已触发重连"), nil
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
		CurrentStepId:      item.CurrentStepID,
		LastError:          item.LastError,
		PendingAssignCount: item.PendingAssign,
		PendingStopCount:   item.PendingStop,
	}
	if !item.LastSeen.IsZero() {
		row.LastSeenAt = item.LastSeen.Format(time.RFC3339)
	}
	return row
}

func validateUUIDField(raw string, field string) error {
	value := strings.TrimSpace(raw)
	if value == "" {
		return status.Errorf(codes.InvalidArgument, "%s 不能为空", field)
	}
	if _, err := uuid.Parse(value); err != nil {
		return status.Errorf(codes.InvalidArgument, "%s 不是合法 UUID: %v", field, err)
	}
	return nil
}

func normalizeCommandID(commandID string) string {
	commandID = strings.TrimSpace(commandID)
	if commandID == "" {
		return uuid.NewString()
	}
	return commandID
}

func buildRuntimeDomainCommandResponse(commandID, status, message string) *dispatcheradminv1.CommandResponse {
	return &dispatcheradminv1.CommandResponse{
		CommandId: commandID,
		Status:    strings.TrimSpace(status),
		Message:   strings.TrimSpace(message),
		RequestId: uuid.NewString(),
	}
}
