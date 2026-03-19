package runtime

import (
	"context"
	"errors"

	"connectrpc.com/connect"
	runtimev1 "github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1"
	"github.com/elebirds/saki/saki-agent/internal/gen/runtime/v1/runtimev1connect"
)

type ControlServer struct {
	runtimev1connect.UnimplementedAgentControlHandler

	service *Service
}

func NewControlServer(service *Service) *ControlServer {
	return &ControlServer{service: service}
}

func (s *ControlServer) AssignTask(ctx context.Context, req *connect.Request[runtimev1.AssignTaskRequest]) (*connect.Response[runtimev1.AssignTaskResponse], error) {
	if s.service == nil {
		return connect.NewResponse(&runtimev1.AssignTaskResponse{Accepted: true}), nil
	}

	if err := s.service.AssignTask(ctx, req.Msg); err != nil {
		code := connect.CodeInternal
		if errors.Is(err, errAgentBusy) {
			code = connect.CodeFailedPrecondition
		}
		return nil, connect.NewError(code, err)
	}

	return connect.NewResponse(&runtimev1.AssignTaskResponse{Accepted: true}), nil
}

func (s *ControlServer) StopTask(ctx context.Context, req *connect.Request[runtimev1.StopTaskRequest]) (*connect.Response[runtimev1.StopTaskResponse], error) {
	if s.service != nil {
		if err := s.service.StopTask(ctx, req.Msg); err != nil {
			return nil, connect.NewError(connect.CodeInternal, err)
		}
	}
	return connect.NewResponse(&runtimev1.StopTaskResponse{Accepted: true}), nil
}
