package apihttp

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"time"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapi "github.com/elebirds/saki/saki-controlplane/internal/modules/access/apihttp"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	annotationapi "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/apihttp"
	annotationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/annotation/app"
	assetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/asset/apihttp"
	datasetapi "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/apihttp"
	datasetapp "github.com/elebirds/saki/saki-controlplane/internal/modules/dataset/app"
	identityapi "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/apihttp"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	importingapi "github.com/elebirds/saki/saki-controlplane/internal/modules/importing/apihttp"
	projectapi "github.com/elebirds/saki/saki-controlplane/internal/modules/project/apihttp"
	projectapp "github.com/elebirds/saki/saki-controlplane/internal/modules/project/app"
	runtimeapi "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/apihttp"
	runtimequeries "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/queries"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type Dependencies struct {
	Authenticator       *accessapp.Authenticator
	ClaimsStore         accessapp.ClaimsStore
	Identity            *identityapi.Handlers
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
		asset: assetapi.NewHandlers(deps.Asset),
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

	return authctx.Middleware(deps.Authenticator)(baseHandler), nil
}

func (s *Server) Healthz(context.Context) (*openapi.HealthResponse, error) {
	return &openapi.HealthResponse{
		Status: "ok",
	}, nil
}

func (s *Server) NewError(_ context.Context, err error) *openapi.ErrorResponseStatusCode {
	return mapError(err)
}

func (s *Server) ChangePassword(ctx context.Context, req *openapi.AuthChangePasswordRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.ChangePassword(ctx, req)
}

func (s *Server) Login(ctx context.Context, req *openapi.AuthLoginRequest) (*openapi.AuthSessionResponse, error) {
	// 关键设计：/auth/login 在迁移期同时承载“新的人类身份登录”和“旧 bootstrap principal 免密登录”。
	// 这里必须显式分流并禁止协议混用，避免把迁移兼容层扩散成长期双主协议。
	if legacyUserID, ok := req.GetUserID().Get(); ok {
		if req.GetIdentifier().IsSet() || req.GetPassword().IsSet() {
			return nil, newBadRequest("user_id login cannot be mixed with identifier/password")
		}
		return s.loginLegacyBootstrap(ctx, legacyUserID)
	}

	identifier, hasIdentifier := req.GetIdentifier().Get()
	password, hasPassword := req.GetPassword().Get()
	if !hasIdentifier || !hasPassword {
		return nil, newBadRequest("identifier and password are required")
	}
	if identifier == "" || password == "" {
		return nil, newBadRequest("identifier and password are required")
	}
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.Login(ctx, req)
}

func (s *Server) InitAssetUpload(ctx context.Context, req *openapi.AssetUploadInitRequest) (*openapi.AssetUploadInitResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.InitAssetUpload(ctx, req)
}

func (s *Server) CancelAssetUpload(ctx context.Context, params openapi.CancelAssetUploadParams) (*openapi.AssetUploadCancelResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.CancelAssetUpload(ctx, params)
}

func (s *Server) CreateProject(ctx context.Context, req *openapi.CreateProjectRequest) (*openapi.Project, error) {
	return s.project.CreateProject(ctx, req)
}

func (s *Server) CreateDataset(ctx context.Context, req *openapi.CreateDatasetRequest) (*openapi.Dataset, error) {
	return s.dataset.CreateDataset(ctx, req)
}

func (s *Server) InitImportUploadSession(ctx context.Context, req *openapi.ImportUploadInitRequest) (*openapi.ImportUploadInitResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.InitImportUploadSession(ctx, req)
}

func (s *Server) SignImportUploadParts(ctx context.Context, req *openapi.ImportUploadPartSignRequest, params openapi.SignImportUploadPartsParams) (*openapi.ImportUploadPartSignResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.SignImportUploadParts(ctx, req, params)
}

func (s *Server) CompleteImportUploadSession(ctx context.Context, req *openapi.ImportUploadCompleteRequest, params openapi.CompleteImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.CompleteImportUploadSession(ctx, req, params)
}

func (s *Server) AbortImportUploadSession(ctx context.Context, params openapi.AbortImportUploadSessionParams) (*openapi.ImportUploadAbortResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.AbortImportUploadSession(ctx, params)
}

func (s *Server) GetImportUploadSession(ctx context.Context, params openapi.GetImportUploadSessionParams) (*openapi.ImportUploadSession, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportUploadSession(ctx, params)
}

func (s *Server) PrepareProjectAnnotationImport(ctx context.Context, req *openapi.PrepareProjectAnnotationImportRequest, params openapi.PrepareProjectAnnotationImportParams) (*openapi.PrepareProjectAnnotationImportResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.PrepareProjectAnnotationImport(ctx, req, params)
}

func (s *Server) ExecuteProjectAnnotationImport(ctx context.Context, req *openapi.ExecuteProjectAnnotationImportRequest, params openapi.ExecuteProjectAnnotationImportParams) (*openapi.ImportTaskCreateResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.ExecuteProjectAnnotationImport(ctx, req, params)
}

func (s *Server) GetImportTask(ctx context.Context, params openapi.GetImportTaskParams) (*openapi.ImportTaskStatusResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportTask(ctx, params)
}

func (s *Server) GetImportTaskResult(ctx context.Context, params openapi.GetImportTaskResultParams) (*openapi.ImportTaskResultResponse, error) {
	if s.importing == nil || !s.importing.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.importing.GetImportTaskResult(ctx, params)
}

func (s *Server) CancelRuntimeTask(ctx context.Context, params openapi.CancelRuntimeTaskParams) (*openapi.RuntimeCommandResponse, error) {
	return s.runtime.CancelRuntimeTask(ctx, params)
}

func (s *Server) CreateSampleAnnotations(ctx context.Context, req *openapi.CreateAnnotationRequest, params openapi.CreateSampleAnnotationsParams) ([]openapi.Annotation, error) {
	return s.annotation.CreateSampleAnnotations(ctx, req, params)
}

func (s *Server) CompleteAssetUpload(ctx context.Context, req *openapi.AssetCompleteRequest, params openapi.CompleteAssetUploadParams) (*openapi.Asset, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.CompleteAssetUpload(ctx, req, params)
}

func (s *Server) GetCurrentUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	if s.identity != nil {
		response, err := s.identity.GetCurrentUser(ctx)
		if err == nil {
			return response, nil
		}
		if !errors.Is(err, identityapp.ErrInvalidCredentials) {
			return nil, err
		}
	}
	return s.currentLegacyBootstrapUser(ctx)
}

func (s *Server) GetSystemSettings(ctx context.Context) (*openapi.SystemSettingsResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.GetSystemSettings(ctx)
}

func (s *Server) GetSystemStatus(ctx context.Context) (*openapi.SystemStatusResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.GetSystemStatus(ctx)
}

func (s *Server) GetSystemTypes(ctx context.Context) (*openapi.SystemTypesResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.GetSystemTypes(ctx)
}

func (s *Server) PatchSystemSettings(ctx context.Context, req *openapi.SystemSettingsPatchRequest) (*openapi.SystemSettingsResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.PatchSystemSettings(ctx, req)
}

func (s *Server) SetupSystem(ctx context.Context, req *openapi.SystemSetupRequest) (*openapi.AuthSessionResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.SetupSystem(ctx, req)
}

func (s *Server) GetAsset(ctx context.Context, params openapi.GetAssetParams) (*openapi.Asset, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.GetAsset(ctx, params)
}

func (s *Server) GetDataset(ctx context.Context, params openapi.GetDatasetParams) (openapi.GetDatasetRes, error) {
	return s.dataset.GetDataset(ctx, params)
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

func (s *Server) ListDatasets(ctx context.Context, params openapi.ListDatasetsParams) (*openapi.DatasetListResponse, error) {
	return s.dataset.ListDatasets(ctx, params)
}

func (s *Server) LinkProjectDatasets(ctx context.Context, req *openapi.ProjectDatasetLinkRequest, params openapi.LinkProjectDatasetsParams) (openapi.LinkProjectDatasetsRes, error) {
	return s.project.LinkProjectDatasets(ctx, req, params)
}

func (s *Server) ListProjectDatasetDetails(ctx context.Context, params openapi.ListProjectDatasetDetailsParams) (openapi.ListProjectDatasetDetailsRes, error) {
	return s.project.ListProjectDatasetDetails(ctx, params)
}

func (s *Server) ListProjectDatasets(ctx context.Context, params openapi.ListProjectDatasetsParams) (openapi.ListProjectDatasetsRes, error) {
	return s.project.ListProjectDatasets(ctx, params)
}

func (s *Server) ListRuntimeAgents(ctx context.Context) ([]openapi.RuntimeAgent, error) {
	return s.runtime.ListRuntimeAgents(ctx)
}

func (s *Server) ListSampleAnnotations(ctx context.Context, params openapi.ListSampleAnnotationsParams) ([]openapi.Annotation, error) {
	return s.annotation.ListSampleAnnotations(ctx, params)
}

func (s *Server) SignAssetDownload(ctx context.Context, req *openapi.AssetDownloadSignRequest, params openapi.SignAssetDownloadParams) (*openapi.AssetDownloadSignResponse, error) {
	if s.asset == nil || !s.asset.Enabled() {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.asset.SignAssetDownload(ctx, req, params)
}

func (s *Server) UpdateDataset(ctx context.Context, req *openapi.UpdateDatasetRequest, params openapi.UpdateDatasetParams) (openapi.UpdateDatasetRes, error) {
	return s.dataset.UpdateDataset(ctx, req, params)
}

func (s *Server) UnlinkProjectDatasets(ctx context.Context, req *openapi.ProjectDatasetLinkRequest, params openapi.UnlinkProjectDatasetsParams) (openapi.UnlinkProjectDatasetsRes, error) {
	return s.project.UnlinkProjectDatasets(ctx, req, params)
}

func (s *Server) DeleteDataset(ctx context.Context, params openapi.DeleteDatasetParams) (openapi.DeleteDatasetRes, error) {
	return s.dataset.DeleteDataset(ctx, params)
}

func (s *Server) DeleteDatasetSample(ctx context.Context, params openapi.DeleteDatasetSampleParams) (openapi.DeleteDatasetSampleRes, error) {
	return s.dataset.DeleteDatasetSample(ctx, params)
}

func (s *Server) RequirePermission(ctx context.Context, params openapi.RequirePermissionParams) error {
	return s.access.RequirePermission(ctx, params)
}

func (s *Server) LogoutAuthSession(ctx context.Context, req *openapi.AuthLogoutRequest) error {
	if s.identity == nil {
		return ogenhttp.ErrNotImplemented
	}
	return s.identity.LogoutAuthSession(ctx, req)
}

func (s *Server) RefreshAuthSession(ctx context.Context, req *openapi.AuthRefreshRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.RefreshAuthSession(ctx, req)
}

func (s *Server) RegisterAuthUser(ctx context.Context, req *openapi.AuthRegisterRequest) (*openapi.AuthSessionResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.RegisterAuthUser(ctx, req)
}

func (s *Server) loginLegacyBootstrap(ctx context.Context, userID string) (*openapi.AuthSessionResponse, error) {
	if s.authenticator == nil {
		return nil, ogenhttp.ErrNotImplemented
	}

	token, err := s.authenticator.IssueBootstrapTokenContext(ctx, userID)
	if err != nil {
		return nil, err
	}
	claims, err := s.authenticator.ParseToken(token)
	if err != nil {
		return nil, err
	}

	expiresIn := int64(time.Until(claims.ExpiresAt).Seconds())
	if expiresIn < 0 {
		expiresIn = 0
	}

	response := &openapi.AuthSessionResponse{
		AccessToken:        token,
		RefreshToken:       "",
		ExpiresIn:          expiresIn,
		MustChangePassword: false,
		Permissions:        append([]string{}, claims.Permissions...),
		User: openapi.AuthSessionUser{
			PrincipalID: claims.PrincipalID.String(),
			Email:       legacyBootstrapEmailAlias(claims.UserID),
			FullName:    "",
		},
	}
	// 关键设计：legacy bootstrap 登录只保留短期 access token，不再补造 refresh session。
	// 为兼容旧前端和 smoke，仍额外回填 token/user_id/permissions 这些历史字段别名。
	response.Token.SetTo(token)
	response.UserID.SetTo(claims.UserID)
	return response, nil
}

func (s *Server) currentLegacyBootstrapUser(ctx context.Context) (*openapi.CurrentUserResponse, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}

	response := &openapi.CurrentUserResponse{
		User: openapi.AuthSessionUser{
			PrincipalID: claims.PrincipalID.String(),
			Email:       legacyBootstrapEmailAlias(claims.UserID),
			FullName:    "",
		},
		SystemRoles:        []string{},
		Permissions:        append([]string(nil), claims.Permissions...),
		MustChangePassword: false,
	}
	response.UserID.SetTo(claims.UserID)
	return response, nil
}

func legacyBootstrapEmailAlias(userID string) string {
	sum := sha256.Sum256([]byte(userID))
	// 关键设计：当前 OpenAPI 仍要求 user.email 满足 email 格式。
	// 对 legacy bootstrap principal，这里生成一个不可投递的稳定别名，避免把 user_id 伪装成真实邮箱；
	// 迁移期客户端应读取顶层 user_id，而不是把这个兼容别名当成业务身份字段。
	return "bootstrap-" + hex.EncodeToString(sum[:8]) + "@legacy.saki.invalid"
}
