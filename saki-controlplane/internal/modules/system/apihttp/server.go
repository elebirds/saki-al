package apihttp

import (
	"errors"
	"net/http"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	publictransport "github.com/elebirds/saki/saki-controlplane/internal/app/publicapi"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapi "github.com/elebirds/saki/saki-controlplane/internal/modules/access/apihttp"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationapi "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/apihttp"
	annotationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app"
	assetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/apihttp"
	authorizationapi "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/apihttp"
	datasetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/apihttp"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	identityapi "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/apihttp"
	importingapi "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/apihttp"
	projectapi "github.com/elebirds/saki/saki-controlplane/internal/modules/project/apihttp"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimeapi "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/apihttp"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
)

type Dependencies struct {
	Authenticator       *accessapp.Authenticator
	ClaimsStore         accessapp.ClaimsStore
	Identity            *identityapi.Handlers
	Authorization       *authorizationapi.Handlers
	System              *Handlers
	DatasetStore        datasetapp.Store
	DatasetDelete       *datasetapp.DeleteDatasetUseCase
	DatasetDeleteSample *datasetapp.DeleteSampleUseCase
	ProjectStore        projectapp.Store
	RuntimeStore        runtimequeries.AdminStore
	RuntimeTaskCanceler runtimequeries.RuntimeTaskCanceler
	AnnotationSamples   annotationapp.SampleStore
	AnnotationDatasets  annotationapp.DatasetStore
	AnnotationStore     annotationapp.AnnotationStore
	AnnotationMapper    annotationapp.Mapper
	Asset               assetapi.Dependencies
	Importing           importingapi.Dependencies
}

type Server struct {
	openapi.UnimplementedHandler

	authenticator *accessapp.Authenticator
	access        *accessapi.Handlers
	annotation    *annotationapi.Handlers
	asset         *assetapi.Handlers
	authorization *authorizationapi.Handlers
	dataset       *datasetapi.Handlers
	identity      *identityapi.Handlers
	importing     *importingapi.Handlers
	project       *projectapi.Handlers
	runtime       *runtimeapi.Handlers
	system        *Handlers
}

func NewHandler(deps Dependencies) (*Server, error) {
	if deps.Authenticator == nil {
		return nil, errors.New("authenticator is required")
	}
	if deps.ProjectStore == nil {
		return nil, errors.New("project store is required")
	}
	if deps.DatasetStore == nil {
		return nil, errors.New("dataset store is required")
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
	if deps.AnnotationDatasets == nil {
		return nil, errors.New("annotation dataset store is required")
	}
	if deps.AnnotationStore == nil {
		return nil, errors.New("annotation store is required")
	}
	return &Server{
		authenticator: deps.Authenticator,
		access:        accessapi.NewHandlers(deps.Authenticator),
		annotation: annotationapi.NewHandlersWithDependencies(
			deps.AnnotationSamples,
			deps.AnnotationDatasets,
			deps.ProjectStore,
			deps.AnnotationStore,
			deps.AnnotationMapper,
		),
		asset:         assetapi.NewHandlers(deps.Asset),
		authorization: deps.Authorization,
		dataset: datasetapi.NewHandlersWithDependencies(datasetapi.Dependencies{
			Store:        deps.DatasetStore,
			Delete:       deps.DatasetDelete,
			DeleteSample: deps.DatasetDeleteSample,
		}),
		identity:  deps.Identity,
		importing: importingapi.NewHandlers(deps.Importing),
		project:   projectapi.NewHandlers(deps.ProjectStore, deps.DatasetStore),
		runtime: runtimeapi.NewHandlers(runtimeapi.Dependencies{
			Store:    deps.RuntimeStore,
			Commands: runtimequeries.NewIssueRuntimeCommandUseCase(deps.RuntimeTaskCanceler),
		}),
		system: deps.System,
	}, nil
}

func NewHTTPHandler(deps Dependencies) (http.Handler, error) {
	if deps.ClaimsStore == nil {
		return nil, errors.New("access claims store is required")
	}

	handler, err := NewHandler(deps)
	if err != nil {
		return nil, err
	}

	server, err := openapi.NewServer(handler, openapi.WithErrorHandler(writeMappedError))
	if err != nil {
		return nil, err
	}

	baseHandler := http.Handler(server)
	if handler.importing != nil && handler.importing.Enabled() {
		baseHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if handler.importing.TryServeHTTP(w, r) {
				return
			}
			server.ServeHTTP(w, r)
		})
	}
	baseHandler = authctx.Middleware(deps.Authenticator)(baseHandler)

	// 关键设计：已退役 public API 路由属于统一 transport 契约，而不是某个业务模块自己的责任。
	// 这里把 tombstone 提升到公共入口层，确保旧客户端即使带坏 token，仍然先收到 404 而不是 401。
	return publictransport.WithRemovedRoutes(baseHandler, publictransport.RemovedLegacyRoutes...), nil
}
