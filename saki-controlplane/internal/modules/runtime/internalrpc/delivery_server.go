package internalrpc

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"github.com/google/uuid"

	runtimev1 "github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1"
	"github.com/elebirds/saki/saki-controlplane/internal/gen/proto/runtime/v1/runtimev1connect"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

const (
	defaultPullClaimTTL      = 30 * time.Second
	defaultPullBatchSize     = int32(8)
	defaultPullPollInterval  = 100 * time.Millisecond
	receivedCommandAckState  = "received"
)

type deliveryCommandStore interface {
	ClaimForPull(ctx context.Context, agentID string, limit int32, claimUntil time.Time) ([]runtimerepo.AgentCommand, error)
	Ack(ctx context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error
	MarkFinished(ctx context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error
}

type DeliveryServer struct {
	runtimev1connect.UnimplementedAgentDeliveryHandler

	commands deliveryCommandStore
	now      func() time.Time
	claimTTL time.Duration
}

func NewDeliveryServer(commands deliveryCommandStore) *DeliveryServer {
	return &DeliveryServer{
		commands: commands,
		now:      time.Now,
		claimTTL: defaultPullClaimTTL,
	}
}

func (s *DeliveryServer) PullCommands(ctx context.Context, req *connect.Request[runtimev1.PullCommandsRequest]) (*connect.Response[runtimev1.PullCommandsResponse], error) {
	items, err := s.claimUntilAvailable(ctx, req.Msg.GetAgentId(), normalizePullBatchSize(req.Msg.GetMaxItems()), req.Msg.GetWaitTimeoutMs())
	if err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	commands := make([]*runtimev1.PulledCommand, 0, len(items))
	for _, item := range items {
		command, err := pulledCommandFromRepo(item)
		if err != nil {
			return nil, connect.NewError(connect.CodeInternal, err)
		}
		commands = append(commands, command)
	}

	return connect.NewResponse(&runtimev1.PullCommandsResponse{
		Commands: commands,
	}), nil
}

func (s *DeliveryServer) AckCommand(ctx context.Context, req *connect.Request[runtimev1.AckCommandRequest]) (*connect.Response[runtimev1.AckCommandResponse], error) {
	if req.Msg.GetState() != receivedCommandAckState {
		return nil, connect.NewError(connect.CodeInvalidArgument, fmt.Errorf("unsupported ack state: %s", req.Msg.GetState()))
	}

	commandID, err := uuid.Parse(req.Msg.GetCommandId())
	if err != nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, err)
	}
	claimToken, err := uuid.Parse(req.Msg.GetDeliveryToken())
	if err != nil {
		return nil, connect.NewError(connect.CodeInvalidArgument, err)
	}

	at := s.now().UTC()
	// pull 模式下 delivery 动作发生在 agent 侧；
	// agent 一旦成功把命令交给本地 runtime，就可以把命令标记为 acked+finished，避免重复投递。
	if err := s.commands.Ack(ctx, commandID, claimToken, at); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}
	if err := s.commands.MarkFinished(ctx, commandID, claimToken, at); err != nil {
		return nil, connect.NewError(connect.CodeInternal, err)
	}

	return connect.NewResponse(&runtimev1.AckCommandResponse{Accepted: true}), nil
}

func (s *DeliveryServer) claimUntilAvailable(ctx context.Context, agentID string, limit int32, waitTimeoutMs int64) ([]runtimerepo.AgentCommand, error) {
	if s.commands == nil {
		return nil, nil
	}

	deadline := s.now().Add(time.Duration(waitTimeoutMs) * time.Millisecond)
	for {
		items, err := s.commands.ClaimForPull(ctx, agentID, limit, s.now().Add(s.claimTTL))
		if err != nil || len(items) > 0 || waitTimeoutMs <= 0 || !s.now().Before(deadline) {
			return items, err
		}

		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(defaultPullPollInterval):
		}
	}
}

func pulledCommandFromRepo(item runtimerepo.AgentCommand) (*runtimev1.PulledCommand, error) {
	if item.ClaimToken == nil {
		return nil, errors.New("claimed pull command missing claim token")
	}

	executionID, err := executionIDFromCommandPayload(item.CommandType, item.Payload)
	if err != nil {
		return nil, err
	}

	return &runtimev1.PulledCommand{
		CommandId:     item.CommandID.String(),
		CommandType:   item.CommandType,
		TaskId:        item.TaskID.String(),
		ExecutionId:   executionID,
		Payload:       append([]byte(nil), item.Payload...),
		DeliveryToken: item.ClaimToken.String(),
	}, nil
}

func executionIDFromCommandPayload(commandType string, payload []byte) (string, error) {
	var envelope struct {
		ExecutionID string `json:"execution_id"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return "", fmt.Errorf("decode %s command payload: %w", commandType, err)
	}
	if envelope.ExecutionID == "" {
		return "", fmt.Errorf("%s command missing execution_id", commandType)
	}
	return envelope.ExecutionID, nil
}

func normalizePullBatchSize(limit int32) int32 {
	if limit <= 0 {
		return defaultPullBatchSize
	}
	return limit
}
