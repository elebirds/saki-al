package apihttp

import (
	"context"
	"errors"
	"net/http"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapi "github.com/elebirds/saki/saki-controlplane/internal/modules/access/apihttp"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationapi "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/apihttp"
	annotationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app"
	projectapi "github.com/elebirds/saki/saki-controlplane/internal/modules/project/apihttp"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimeapi "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/apihttp"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
)

type Dependencies struct {
	Authenticator       *accessapp.Authenticator
	ProjectStore        projectapp.Store
	RuntimeStore        runtimequeries.AdminStore
	RuntimeTaskCanceler runtimequeries.RuntimeTaskCanceler
	AnnotationSamples   annotationapp.SampleStore
	AnnotationStore     annotationapp.AnnotationStore
	AnnotationMapper    annotationapp.Mapper
}

type Server struct {
	openapi.UnimplementedHandler

	access     *accessapi.Handlers
	annotation *annotationapi.Handlers
	project    *projectapi.Handlers
	runtime    *runtimeapi.Handlers
}

func NewHandler(deps Dependencies) (*Server, error) {
	if deps.Authenticator == nil {
		return nil, errors.New("authenticator is required")
	}
	if deps.ProjectStore == nil {
		return nil, errors.New("project store is required")
	}
	if deps.RuntimeStore == nil {
		return nil, errors.New("runtime store is required")
	}
	if deps.RuntimeTaskCanceler == nil {
		return nil, errors.New("runtime task canceler is required")
	}
	if deps.AnnotationSamples == nil {
		return nil, errors.New("annotation sample store is required")
	}
	if deps.AnnotationStore == nil {
		return nil, errors.New("annotation store is required")
	}
	return &Server{
		access: accessapi.NewHandlers(deps.Authenticator),
		annotation: annotationapi.NewHandlers(
			deps.AnnotationSamples,
			deps.AnnotationStore,
			deps.AnnotationMapper,
		),
		project: projectapi.NewHandlers(deps.ProjectStore),
		runtime: runtimeapi.NewHandlers(runtimeapi.Dependencies{
			Store:    deps.RuntimeStore,
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(deps.RuntimeTaskCanceler),
		}),
	}, nil
}

func NewHTTPHandler(deps Dependencies) (http.Handler, error) {
	handler, err := NewHandler(deps)
	if err != nil {
		return nil, err
	}

	server, err := openapi.NewServer(handler, openapi.WithErrorHandler(writeMappedError))
	if err != nil {
		return nil, err
	}

	return authctx.Middleware(deps.Authenticator)(server), nil
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

func (s *Server) CreateProject(ctx context.Context, req *openapi.CreateProjectRequest) (*openapi.Project, error) {
	return s.project.CreateProject(ctx, req)
}

func (s *Server) CancelRuntimeTask(ctx context.Context, params openapi.CancelRuntimeTaskParams) (*openapi.RuntimeCommandResponse, error) {
	return s.runtime.CancelRuntimeTask(ctx, params)
}

func (s *Server) CreateSampleAnnotations(ctx context.Context, req *openapi.CreateAnnotationRequest, params openapi.CreateSampleAnnotationsParams) ([]openapi.Annotation, error) {
	return s.annotation.CreateSampleAnnotations(ctx, req, params)
}

func (s *Server) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	return s.access.GetCurrentUser(ctx)
}

func (s *Server) GetProject(ctx context.Context, params openapi.GetProjectParams) (*openapi.Project, error) {
	return s.project.GetProject(ctx, params)
}

func (s *Server) GetRuntimeSummary(ctx context.Context) (*openapi.RuntimeSummaryResponse, error) {
	return s.runtime.GetRuntimeSummary(ctx)
}

func (s *Server) ListProjects(ctx context.Context) ([]openapi.Project, error) {
	return s.project.ListProjects(ctx)
}

func (s *Server) ListRuntimeExecutors(ctx context.Context) ([]openapi.RuntimeExecutor, error) {
	return s.runtime.ListRuntimeExecutors(ctx)
}

func (s *Server) ListSampleAnnotations(ctx context.Context, params openapi.ListSampleAnnotationsParams) ([]openapi.Annotation, error) {
	return s.annotation.ListSampleAnnotations(ctx, params)
}

func (s *Server) RequirePermission(ctx context.Context, params openapi.RequirePermissionParams) error {
	return s.access.RequirePermission(ctx, params)
}
