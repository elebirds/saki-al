package apihttp

import (
	"context"
	"net/http"
	"time"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapi "github.com/elebirds/saki/saki-controlplane/internal/modules/access/apihttp"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
)

type Server struct {
	openapi.UnimplementedHandler

	access *accessapi.Handlers
}

func NewHandler() *Server {
	authenticator := accessapp.NewAuthenticator("dev-secret", 24*time.Hour)
	return &Server{
		access: accessapi.NewHandlers(authenticator),
	}
}

func NewHTTPHandler() (http.Handler, error) {
	handler := NewHandler()
	server, err := openapi.NewServer(handler, openapi.WithErrorHandler(writeMappedError))
	if err != nil {
		return nil, err
	}

	return authctx.Middleware(accessapp.NewAuthenticator("dev-secret", 24*time.Hour))(server), nil
}

func (s *Server) Healthz(context.Context) (*openapi.HealthResponse, error) {
	return &openapi.HealthResponse{
		Status: "ok",
	}, nil
}

func (s *Server) NewError(_ context.Context, err error) *openapi.ErrorResponseStatusCode {
	return mapError(err)
}

func (s *Server) Login(ctx context.Context, req *openapi.LoginRequest) (*openapi.AuthTokenResponse, error) {
	return s.access.Login(ctx, req)
}

func (s *Server) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	return s.access.GetCurrentUser(ctx)
}

func (s *Server) RequirePermission(ctx context.Context, params openapi.RequirePermissionParams) error {
	return s.access.RequirePermission(ctx, params)
}
