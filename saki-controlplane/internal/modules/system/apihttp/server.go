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
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
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
	baseHandler = withRemovedLegacyRoutes(baseHandler)

	return authctx.Middleware(deps.Authenticator)(baseHandler), nil
}

func withRemovedLegacyRoutes(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// 关键设计：旧 alias 一旦退役，就要在 transport 层显式返回 404，
		// 不能让它们因为动态路由碰巧落到其他 handler（例如 /roles/{role_id}）而表现成 400/501。
		if r.Method == http.MethodGet && (r.URL.Path == "/roles/permission-catalog" || r.URL.Path == "/permissions/catalog") {
			http.NotFound(w, r)
			return
		}
		next.ServeHTTP(w, r)
	})
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
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.GetCurrentUser(ctx)
}

func (s *Server) CreateRole(ctx context.Context, req *openapi.RoleCreateRequest) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.CreateRole(ctx, req)
}

func (s *Server) GetRole(ctx context.Context, params openapi.GetRoleParams) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetRole(ctx, params)
}

func (s *Server) UpdateRole(ctx context.Context, req *openapi.RoleUpdateRequest, params openapi.UpdateRoleParams) (*openapi.RoleListItem, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.UpdateRole(ctx, req, params)
}

func (s *Server) DeleteRole(ctx context.Context, params openapi.DeleteRoleParams) error {
	if s.authorization == nil {
		return ogenhttp.ErrNotImplemented
	}
	return s.authorization.DeleteRole(ctx, params)
}

func (s *Server) GetSystemPermissions(ctx context.Context) (*openapi.SystemPermissionsResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetSystemPermissions(ctx)
}

func (s *Server) GetResourcePermissions(ctx context.Context, params openapi.GetResourcePermissionsParams) (*openapi.ResourcePermissionsResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.GetResourcePermissions(ctx, params)
}

func (s *Server) ListRoles(ctx context.Context, params openapi.ListRolesParams) (*openapi.RoleListResponse, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.authorization.ListRoles(ctx, params)
}

func (s *Server) ListUserSystemRoles(ctx context.Context, params openapi.ListUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.UserID); err != nil {
		return nil, newBadRequest("invalid user_id")
	}
	return s.authorization.ListUserSystemRoles(ctx, params)
}

func (s *Server) ReplaceUserSystemRoles(ctx context.Context, req *openapi.ReplaceUserSystemRolesRequest, params openapi.ReplaceUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.UserID); err != nil {
		return nil, newBadRequest("invalid user_id")
	}
	return s.authorization.ReplaceUserSystemRoles(ctx, req, params)
}

func (s *Server) ListUsers(ctx context.Context, params openapi.ListUsersParams) (*openapi.UserListResponse, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.ListUsers(ctx, params)
}

func (s *Server) CreateUser(ctx context.Context, req *openapi.UserCreateRequest) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.identity.CreateUser(ctx, req)
}

func (s *Server) GetUser(ctx context.Context, params openapi.GetUserParams) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.UserID); err != nil {
		return nil, newBadRequest("invalid user_id")
	}
	return s.identity.GetUser(ctx, params)
}

func (s *Server) UpdateUser(ctx context.Context, req *openapi.UserUpdateRequest, params openapi.UpdateUserParams) (*openapi.UserListItem, error) {
	if s.identity == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.UserID); err != nil {
		return nil, newBadRequest("invalid user_id")
	}
	return s.identity.UpdateUser(ctx, req, params)
}

func (s *Server) DeleteUser(ctx context.Context, params openapi.DeleteUserParams) error {
	if s.identity == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.UserID); err != nil {
		return newBadRequest("invalid user_id")
	}
	return s.identity.DeleteUser(ctx, params)
}

func (s *Server) ListAvailableDatasetRoles(ctx context.Context, params openapi.ListAvailableDatasetRolesParams) ([]openapi.ResourceRoleInfo, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.DatasetID); err != nil {
		return nil, newBadRequest("invalid dataset_id")
	}
	return s.authorization.ListAvailableDatasetRoles(ctx, params)
}

func (s *Server) ListDatasetMembers(ctx context.Context, params openapi.ListDatasetMembersParams) ([]openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.DatasetID); err != nil {
		return nil, newBadRequest("invalid dataset_id")
	}
	return s.authorization.ListDatasetMembers(ctx, params)
}

func (s *Server) CreateDatasetMember(ctx context.Context, req *openapi.ResourceMemberCreateRequest, params openapi.CreateDatasetMemberParams) (*openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.DatasetID); err != nil {
		return nil, newBadRequest("invalid dataset_id")
	}
	return s.authorization.CreateDatasetMember(ctx, req, params)
}

func (s *Server) UpdateDatasetMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateDatasetMemberParams) (*openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.DatasetID); err != nil {
		return nil, newBadRequest("invalid dataset_id")
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.authorization.UpdateDatasetMember(ctx, req, params)
}

func (s *Server) DeleteDatasetMember(ctx context.Context, params openapi.DeleteDatasetMemberParams) error {
	if s.authorization == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.DatasetID); err != nil {
		return newBadRequest("invalid dataset_id")
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return newBadRequest("invalid principal_id")
	}
	return s.authorization.DeleteDatasetMember(ctx, params)
}

func (s *Server) ListAvailableProjectRoles(ctx context.Context, params openapi.ListAvailableProjectRolesParams) ([]openapi.ResourceRoleInfo, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.ProjectID); err != nil {
		return nil, newBadRequest("invalid project_id")
	}
	return s.authorization.ListAvailableProjectRoles(ctx, params)
}

func (s *Server) ListProjectMembers(ctx context.Context, params openapi.ListProjectMembersParams) ([]openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.ProjectID); err != nil {
		return nil, newBadRequest("invalid project_id")
	}
	return s.authorization.ListProjectMembers(ctx, params)
}

func (s *Server) CreateProjectMember(ctx context.Context, req *openapi.ResourceMemberCreateRequest, params openapi.CreateProjectMemberParams) (*openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.ProjectID); err != nil {
		return nil, newBadRequest("invalid project_id")
	}
	return s.authorization.CreateProjectMember(ctx, req, params)
}

func (s *Server) UpdateProjectMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateProjectMemberParams) (*openapi.ResourceMember, error) {
	if s.authorization == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.ProjectID); err != nil {
		return nil, newBadRequest("invalid project_id")
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return nil, newBadRequest("invalid principal_id")
	}
	return s.authorization.UpdateProjectMember(ctx, req, params)
}

func (s *Server) DeleteProjectMember(ctx context.Context, params openapi.DeleteProjectMemberParams) error {
	if s.authorization == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := uuid.Parse(params.ProjectID); err != nil {
		return newBadRequest("invalid project_id")
	}
	if _, err := uuid.Parse(params.PrincipalID); err != nil {
		return newBadRequest("invalid principal_id")
	}
	return s.authorization.DeleteProjectMember(ctx, params)
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
