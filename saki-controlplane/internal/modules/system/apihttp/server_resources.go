package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

// 资源类代理聚合 project/dataset/runtime/annotation/system；只做路由转发与入参兜底校验。
func (s *Server) CreateProject(ctx context.Context, req *openapi.CreateProjectRequest) (*openapi.Project, error) {
	return s.project.CreateProject(ctx, req)
}

func (s *Server) CreateDataset(ctx context.Context, req *openapi.CreateDatasetRequest) (*openapi.Dataset, error) {
	return s.dataset.CreateDataset(ctx, req)
}

func (s *Server) CancelRuntimeTask(ctx context.Context, params openapi.CancelRuntimeTaskParams) (*openapi.RuntimeCommandResponse, error) {
	return s.runtime.CancelRuntimeTask(ctx, params)
}

func (s *Server) CreateSampleAnnotations(ctx context.Context, req *openapi.CreateAnnotationRequest, params openapi.CreateSampleAnnotationsParams) ([]openapi.Annotation, error) {
	return s.annotation.CreateSampleAnnotations(ctx, req, params)
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

func (s *Server) InitializeSystem(ctx context.Context, req *openapi.SystemInitRequest) (*openapi.AuthSessionResponse, error) {
	if s.system == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	return s.system.InitializeSystem(ctx, req)
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
