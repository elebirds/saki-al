package apihttp

import (
	"context"

	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	ogenhttp "github.com/ogen-go/ogen/http"
)

func (h *Handlers) GetCurrentResourcePermissions(ctx context.Context, params openapi.GetCurrentResourcePermissionsParams) (*openapi.CurrentResourcePermissionsResponse, error) {
	if h == nil || h.getCurrentResourcePermissions == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireAnyPermission(ctx)
	if err != nil {
		return nil, err
	}

	resourceID, err := h.requireResourcePermission(ctx, string(params.ResourceType), params.ResourceID)
	if err != nil {
		return nil, err
	}
	result, err := h.getCurrentResourcePermissions.Execute(ctx, claims.PrincipalID, string(params.ResourceType), resourceID)
	if err != nil {
		return nil, err
	}

	response := &openapi.CurrentResourcePermissionsResponse{
		Permissions: authorizationdomain.CanonicalPermissions(result.Permissions),
		IsOwner:     result.IsOwner,
	}
	if result.ResourceRole != nil {
		response.ResourceRole.SetTo(mapResourceRole(*result.ResourceRole))
	}
	return response, nil
}

func (h *Handlers) ListAvailableDatasetRoles(ctx context.Context, params openapi.ListAvailableDatasetRolesParams) ([]openapi.ResourceRoleInfo, error) {
	return h.listAvailableResourceRoles(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID)
}

func (h *Handlers) ListAvailableProjectRoles(ctx context.Context, params openapi.ListAvailableProjectRolesParams) ([]openapi.ResourceRoleInfo, error) {
	return h.listAvailableResourceRoles(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID)
}

func (h *Handlers) ListDatasetMembers(ctx context.Context, params openapi.ListDatasetMembersParams) ([]openapi.ResourceMember, error) {
	return h.listResourceMembers(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID)
}

func (h *Handlers) CreateDatasetMember(ctx context.Context, req *openapi.ResourceMemberCreateRequest, params openapi.CreateDatasetMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, req.GetPrincipalID(), req.GetRoleID())
}

func (h *Handlers) UpdateDatasetMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateDatasetMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, params.PrincipalID, req.GetRoleID())
}

func (h *Handlers) DeleteDatasetMember(ctx context.Context, params openapi.DeleteDatasetMemberParams) error {
	return h.deleteMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, params.PrincipalID)
}

func (h *Handlers) ListProjectMembers(ctx context.Context, params openapi.ListProjectMembersParams) ([]openapi.ResourceMember, error) {
	return h.listResourceMembers(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID)
}

func (h *Handlers) CreateProjectMember(ctx context.Context, req *openapi.ResourceMemberCreateRequest, params openapi.CreateProjectMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, req.GetPrincipalID(), req.GetRoleID())
}

func (h *Handlers) UpdateProjectMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateProjectMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, params.PrincipalID, req.GetRoleID())
}

func (h *Handlers) DeleteProjectMember(ctx context.Context, params openapi.DeleteProjectMemberParams) error {
	return h.deleteMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, params.PrincipalID)
}

func (h *Handlers) listAvailableResourceRoles(ctx context.Context, resourceType string, rawResourceID string) ([]openapi.ResourceRoleInfo, error) {
	if h == nil || h.listAssignableRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return nil, err
	}

	items, err := h.listAssignableRoles.Execute(ctx, resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	result := make([]openapi.ResourceRoleInfo, 0, len(items))
	for _, item := range items {
		result = append(result, mapResourceRole(item))
	}
	return result, nil
}

func (h *Handlers) listResourceMembers(ctx context.Context, resourceType string, rawResourceID string) ([]openapi.ResourceMember, error) {
	if h == nil || h.listResourceMembersEx == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceReadPermission(resourceType), authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return nil, err
	}
	items, err := h.listResourceMembersEx.Execute(ctx, resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	result := make([]openapi.ResourceMember, 0, len(items))
	for _, item := range items {
		result = append(result, mapResourceMember(item))
	}
	return result, nil
}

func (h *Handlers) upsertMember(ctx context.Context, resourceType string, rawResourceID string, rawPrincipalID string, rawRoleID string) (*openapi.ResourceMember, error) {
	if h == nil || h.upsertResourceMember == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return nil, err
	}
	// 关键设计：members transport 合同统一到 principal_id，
	// 避免继续沿用历史 user_id 别名。
	_, principalID, roleID, err := parseMembershipIDs(resourceID.String(), rawPrincipalID, rawRoleID)
	if err != nil {
		return nil, err
	}
	member, err := h.upsertResourceMember.Execute(ctx, authorizationapp.UpsertResourceMemberCommand{
		ResourceType: resourceType,
		ResourceID:   resourceID,
		PrincipalID:  principalID,
		RoleID:       roleID,
	})
	if err != nil {
		return nil, err
	}
	response := mapResourceMember(*member)
	return &response, nil
}

func (h *Handlers) deleteMember(ctx context.Context, resourceType string, rawResourceID string, rawPrincipalID string) error {
	if h == nil || h.deleteResourceMember == nil {
		return ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return err
	}

	_, principalID, _, err := parseMembershipIDs(resourceID.String(), rawPrincipalID, "")
	if err != nil {
		return err
	}
	return h.deleteResourceMember.Execute(ctx, resourceType, resourceID, principalID)
}
