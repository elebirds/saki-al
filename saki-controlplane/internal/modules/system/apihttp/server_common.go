package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
)

// transport 公共出口：只做协议层拼装和错误映射，不承载业务决策。
func (s *Server) Healthz(context.Context) (*openapi.HealthResponse, error) {
	return &openapi.HealthResponse{
		Status: "ok",
	}, nil
}

func (s *Server) NewError(_ context.Context, err error) *openapi.ErrorResponseStatusCode {
	return mapError(err)
}

func (s *Server) RequirePermission(ctx context.Context, params openapi.RequirePermissionParams) error {
	return s.access.RequirePermission(ctx, params)
}
