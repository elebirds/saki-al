package apihttp

import (
	"context"
	"net/http"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
)

type Server struct {
	openapi.UnimplementedHandler
}

func NewHandler() *Server {
	return &Server{}
}

func NewHTTPHandler() (http.Handler, error) {
	return openapi.NewServer(NewHandler(), openapi.WithErrorHandler(writeMappedError))
}

func (s *Server) Healthz(context.Context) (*openapi.HealthResponse, error) {
	return &openapi.HealthResponse{
		Status: "ok",
	}, nil
}

func (s *Server) NewError(_ context.Context, err error) *openapi.ErrorResponseStatusCode {
	return mapError(err)
}
