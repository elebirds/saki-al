package apihttp

import (
	"context"
	"slices"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	ogenhttp "github.com/ogen-go/ogen/http"
)

type ListRolesExecutor interface {
	Execute(ctx context.Context, input authorizationapp.ListRolesInput) (*authorizationapp.RoleListResult, error)
}

type PermissionCatalogExecutor interface {
	Execute(ctx context.Context) (*authorizationapp.PermissionCatalog, error)
}

type UserSystemRolesExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID) ([]authorizationapp.UserSystemRoleBindingView, error)
}

type CreateRoleExecutor interface {
	Execute(ctx context.Context, cmd authorizationapp.CreateRoleCommand) (*authorizationapp.RoleView, error)
}

type GetRoleExecutor interface {
	Execute(ctx context.Context, roleID uuid.UUID) (*authorizationapp.RoleView, error)
}

type UpdateRoleExecutor interface {
	Execute(ctx context.Context, cmd authorizationapp.UpdateRoleCommand) (*authorizationapp.RoleView, error)
}

type DeleteRoleExecutor interface {
	Execute(ctx context.Context, roleID uuid.UUID) error
}

type ReplaceUserSystemRolesExecutor interface {
	Execute(ctx context.Context, cmd authorizationapp.ReplaceUserSystemRolesCommand) ([]authorizationapp.UserSystemRoleBindingView, error)
}

type ListResourceMembersExecutor interface {
	Execute(ctx context.Context, resourceType string, resourceID uuid.UUID) ([]authorizationapp.ResourceMemberView, error)
}

type UpsertResourceMemberExecutor interface {
	Execute(ctx context.Context, cmd authorizationapp.UpsertResourceMemberCommand) (*authorizationapp.ResourceMemberView, error)
}

type DeleteResourceMemberExecutor interface {
	Execute(ctx context.Context, resourceType string, resourceID uuid.UUID, principalID uuid.UUID) error
}

type ListAssignableResourceRolesExecutor interface {
	Execute(ctx context.Context, resourceType string, resourceID uuid.UUID) ([]authorizationapp.ResourceRoleView, error)
}

type GetResourcePermissionsExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) (*authorizationapp.ResourcePermissionsView, error)
}

type ResolveEffectiveResourcePermissionsExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) ([]string, error)
}

type HandlersDeps struct {
	ListRoles             ListRolesExecutor
	PermissionCatalog     PermissionCatalogExecutor
	UserSystemRoles       UserSystemRolesExecutor
	CreateRole            CreateRoleExecutor
	GetRole               GetRoleExecutor
	UpdateRole            UpdateRoleExecutor
	DeleteRole            DeleteRoleExecutor
	ReplaceUserRoles      ReplaceUserSystemRolesExecutor
	ListResourceMembers   ListResourceMembersExecutor
	UpsertResourceMember  UpsertResourceMemberExecutor
	DeleteResourceMember  DeleteResourceMemberExecutor
	ListAssignableRoles   ListAssignableResourceRolesExecutor
	GetResourcePermission GetResourcePermissionsExecutor
	ResolveResourceAccess ResolveEffectiveResourcePermissionsExecutor
}

type Handlers struct {
	listRoles             ListRolesExecutor
	permissionCatalog     PermissionCatalogExecutor
	userSystemRoles       UserSystemRolesExecutor
	createRole            CreateRoleExecutor
	getRole               GetRoleExecutor
	updateRole            UpdateRoleExecutor
	deleteRole            DeleteRoleExecutor
	replaceUserRoles      ReplaceUserSystemRolesExecutor
	listResourceMembersEx ListResourceMembersExecutor
	upsertResourceMember  UpsertResourceMemberExecutor
	deleteResourceMember  DeleteResourceMemberExecutor
	listAssignableRoles   ListAssignableResourceRolesExecutor
	getResourcePermission GetResourcePermissionsExecutor
	resolveResourceAccess ResolveEffectiveResourcePermissionsExecutor
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		listRoles:             deps.ListRoles,
		permissionCatalog:     deps.PermissionCatalog,
		userSystemRoles:       deps.UserSystemRoles,
		createRole:            deps.CreateRole,
		getRole:               deps.GetRole,
		updateRole:            deps.UpdateRole,
		deleteRole:            deps.DeleteRole,
		replaceUserRoles:      deps.ReplaceUserRoles,
		listResourceMembersEx: deps.ListResourceMembers,
		upsertResourceMember:  deps.UpsertResourceMember,
		deleteResourceMember:  deps.DeleteResourceMember,
		listAssignableRoles:   deps.ListAssignableRoles,
		getResourcePermission: deps.GetResourcePermission,
		resolveResourceAccess: deps.ResolveResourceAccess,
	}
}

func (h *Handlers) ListRoles(ctx context.Context, params openapi.ListRolesParams) (*openapi.RoleListResponse, error) {
	if h == nil || h.listRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read"); err != nil {
		return nil, err
	}

	page, _ := params.Page.Get()
	limit, _ := params.Limit.Get()
	roleType, _ := params.Type.Get()

	result, err := h.listRoles.Execute(ctx, authorizationapp.ListRolesInput{
		Page:  int(page),
		Limit: int(limit),
		Type:  string(roleType),
	})
	if err != nil {
		return nil, err
	}

	items := make([]openapi.RoleListItem, 0, len(result.Items))
	for _, item := range result.Items {
		items = append(items, mapRole(item))
	}
	return &openapi.RoleListResponse{
		Items:   items,
		Total:   int32(result.Total),
		Offset:  int32(result.Offset),
		Limit:   int32(result.Limit),
		Size:    int32(result.Size),
		HasMore: result.HasMore,
	}, nil
}

func (h *Handlers) GetPermissionCatalog(ctx context.Context) (*openapi.PermissionCatalogResponse, error) {
	return h.getPermissionCatalog(ctx)
}

func (h *Handlers) CreateRole(ctx context.Context, req *openapi.RoleCreateRequest) (*openapi.RoleListItem, error) {
	if h == nil || h.createRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return nil, err
	}
	if req.GetName() == "" || req.GetDisplayName() == "" {
		return nil, authorizationapp.ErrInvalidRoleInput
	}

	description, hasDescription := req.GetDescription().Get()
	color, hasColor := req.GetColor().Get()
	role, err := h.createRole.Execute(ctx, authorizationapp.CreateRoleCommand{
		Name:        req.GetName(),
		DisplayName: req.GetDisplayName(),
		Description: optStringPtr(description, hasDescription),
		Color:       optStringPtr(color, hasColor),
		Permissions: req.GetPermissions(),
	})
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) GetRole(ctx context.Context, params openapi.GetRoleParams) (*openapi.RoleListItem, error) {
	if h == nil || h.getRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read"); err != nil {
		return nil, err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	role, err := h.getRole.Execute(ctx, roleID)
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) UpdateRole(ctx context.Context, req *openapi.RoleUpdateRequest, params openapi.UpdateRoleParams) (*openapi.RoleListItem, error) {
	if h == nil || h.updateRole == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return nil, err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	displayName, hasDisplayName := req.GetDisplayName().Get()
	description, hasDescription := req.GetDescription().Get()
	color, hasColor := req.GetColor().Get()
	role, err := h.updateRole.Execute(ctx, authorizationapp.UpdateRoleCommand{
		RoleID:            roleID,
		DisplayName:       optStringPtr(displayName, hasDisplayName),
		ChangeDisplayName: hasDisplayName,
		Description:       optStringPtr(description, hasDescription),
		ChangeDescription: hasDescription,
		Color:             optStringPtr(color, hasColor),
		ChangeColor:       hasColor,
		Permissions:       req.GetPermissions(),
		ChangePermissions: req.Permissions != nil,
	})
	if err != nil {
		return nil, err
	}
	response := mapRole(*role)
	return &response, nil
}

func (h *Handlers) DeleteRole(ctx context.Context, params openapi.DeleteRoleParams) error {
	if h == nil || h.deleteRole == nil {
		return ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:write"); err != nil {
		return err
	}

	roleID, err := uuid.Parse(params.RoleID)
	if err != nil {
		return authorizationapp.ErrInvalidRoleInput
	}
	return h.deleteRole.Execute(ctx, roleID)
}

func (h *Handlers) GetSystemPermissions(ctx context.Context) (*openapi.SystemPermissionsResponse, error) {
	if h == nil || h.userSystemRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireAnyPermission(ctx)
	if err != nil {
		return nil, err
	}

	roleBindings, err := h.userSystemRoles.Execute(ctx, claims.PrincipalID)
	if err != nil {
		return nil, err
	}

	roles := make([]openapi.UserRoleInfo, 0, len(roleBindings))
	isSuperAdmin := false
	for _, item := range roleBindings {
		roles = append(roles, openapi.UserRoleInfo{
			ID:          item.RoleID,
			Name:        item.RoleName,
			DisplayName: item.RoleDisplayName,
			Color:       item.RoleColor,
			IsSupremo:   item.RoleIsSupremo,
		})
		if item.RoleName == "super_admin" {
			isSuperAdmin = true
		}
	}

	return &openapi.SystemPermissionsResponse{
		UserID:       claims.UserID,
		SystemRoles:  roles,
		Permissions:  authorizationdomain.CanonicalPermissions(claims.Permissions),
		IsSuperAdmin: isSuperAdmin,
	}, nil
}

func (h *Handlers) ListUserSystemRoles(ctx context.Context, params openapi.ListUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	return h.listUserSystemRoles(ctx, params.UserID)
}

func (h *Handlers) ReplaceUserSystemRoles(ctx context.Context, req *openapi.ReplaceUserSystemRolesRequest, params openapi.ReplaceUserSystemRolesParams) ([]openapi.UserSystemRoleBinding, error) {
	if h == nil || h.replaceUserRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireRoleReplacementPermission(ctx)
	if err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(params.UserID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidRoleInput
	}
	if claims.PrincipalID == principalID {
		return nil, accessapp.ErrForbidden
	}
	result, err := h.replaceUserRoles.Execute(ctx, authorizationapp.ReplaceUserSystemRolesCommand{
		UserID:  principalID,
		RoleIDs: req.GetRoleIds(),
	})
	if err != nil {
		return nil, err
	}
	return mapUserSystemRoleBindings(result), nil
}

func (h *Handlers) GetResourcePermissions(ctx context.Context, params openapi.GetResourcePermissionsParams) (*openapi.ResourcePermissionsResponse, error) {
	if h == nil || h.getResourcePermission == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	claims, err := requireAnyPermission(ctx)
	if err != nil {
		return nil, err
	}

	resourceID, err := uuid.Parse(params.ResourceID)
	if err != nil {
		return nil, authorizationapp.ErrInvalidResourceInput
	}
	result, err := h.getResourcePermission.Execute(ctx, claims.PrincipalID, string(params.ResourceType), resourceID)
	if err != nil {
		return nil, err
	}

	response := &openapi.ResourcePermissionsResponse{
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
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, req.GetUserID(), req.GetRoleID())
}

func (h *Handlers) UpdateDatasetMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateDatasetMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, params.UserID, req.GetRoleID())
}

func (h *Handlers) DeleteDatasetMember(ctx context.Context, params openapi.DeleteDatasetMemberParams) error {
	return h.deleteMember(ctx, authorizationdomain.ResourceTypeDataset, params.DatasetID, params.UserID)
}

func (h *Handlers) ListProjectMembers(ctx context.Context, params openapi.ListProjectMembersParams) ([]openapi.ResourceMember, error) {
	return h.listResourceMembers(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID)
}

func (h *Handlers) CreateProjectMember(ctx context.Context, req *openapi.ResourceMemberCreateRequest, params openapi.CreateProjectMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, req.GetUserID(), req.GetRoleID())
}

func (h *Handlers) UpdateProjectMember(ctx context.Context, req *openapi.ResourceMemberUpdateRequest, params openapi.UpdateProjectMemberParams) (*openapi.ResourceMember, error) {
	return h.upsertMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, params.UserID, req.GetRoleID())
}

func (h *Handlers) DeleteProjectMember(ctx context.Context, params openapi.DeleteProjectMemberParams) error {
	return h.deleteMember(ctx, authorizationdomain.ResourceTypeProject, params.ProjectID, params.UserID)
}

func (h *Handlers) getPermissionCatalog(ctx context.Context) (*openapi.PermissionCatalogResponse, error) {
	if h == nil || h.permissionCatalog == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	if _, err := requireAnyPermission(ctx, "roles:read"); err != nil {
		return nil, err
	}

	catalog, err := h.permissionCatalog.Execute(ctx)
	if err != nil {
		return nil, err
	}
	return &openapi.PermissionCatalogResponse{
		AllPermissions:      authorizationdomain.CanonicalPermissions(catalog.AllPermissions),
		SystemPermissions:   authorizationdomain.CanonicalPermissions(catalog.SystemPermissions),
		ResourcePermissions: authorizationdomain.CanonicalPermissions(catalog.ResourcePermissions),
	}, nil
}

func (h *Handlers) listUserSystemRoles(ctx context.Context, rawUserID string) ([]openapi.UserSystemRoleBinding, error) {
	if h == nil || h.userSystemRoles == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	// 关键设计：查看用户系统角色既可以视为“读用户”，也可以视为“读角色”，
	// 因此这里只接受两种 canonical permission，而不再接纳任何历史别名。
	if _, err := requireAnyPermission(ctx, "roles:read", "users:read"); err != nil {
		return nil, err
	}

	principalID, err := uuid.Parse(rawUserID)
	if err != nil {
		return nil, accessapp.ErrForbidden
	}

	result, err := h.userSystemRoles.Execute(ctx, principalID)
	if err != nil {
		return nil, err
	}

	return mapUserSystemRoleBindings(result), nil
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

func (h *Handlers) upsertMember(ctx context.Context, resourceType string, rawResourceID string, rawUserID string, rawRoleID string) (*openapi.ResourceMember, error) {
	if h == nil || h.upsertResourceMember == nil {
		return nil, ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return nil, err
	}

	_, userID, roleID, err := parseMembershipIDs(resourceID.String(), rawUserID, rawRoleID)
	if err != nil {
		return nil, err
	}
	member, err := h.upsertResourceMember.Execute(ctx, authorizationapp.UpsertResourceMemberCommand{
		ResourceType: resourceType,
		ResourceID:   resourceID,
		UserID:       userID,
		RoleID:       roleID,
	})
	if err != nil {
		return nil, err
	}
	response := mapResourceMember(*member)
	return &response, nil
}

func (h *Handlers) deleteMember(ctx context.Context, resourceType string, rawResourceID string, rawUserID string) error {
	if h == nil || h.deleteResourceMember == nil {
		return ogenhttp.ErrNotImplemented
	}
	resourceID, err := h.requireResourcePermission(ctx, resourceType, rawResourceID, authorizationdomain.ResourceMemberWritePermission(resourceType))
	if err != nil {
		return err
	}

	_, userID, _, err := parseMembershipIDs(resourceID.String(), rawUserID, "")
	if err != nil {
		return err
	}
	return h.deleteResourceMember.Execute(ctx, resourceType, resourceID, userID)
}

func mapRole(item authorizationapp.RoleView) openapi.RoleListItem {
	result := openapi.RoleListItem{
		ID:          item.ID,
		Name:        item.Name,
		DisplayName: item.DisplayName,
		Type:        item.Type,
		BuiltIn:     item.BuiltIn,
		Mutable:     item.Mutable,
		Color:       item.Color,
		IsSupremo:   item.IsSupremo,
		SortOrder:   int32(item.SortOrder),
		IsSystem:    item.IsSystem,
		Permissions: make([]openapi.RolePermissionEntry, 0, len(item.Permissions)),
		CreatedAt:   item.CreatedAt,
		UpdatedAt:   item.UpdatedAt,
	}
	if item.Description != "" {
		result.Description.SetTo(item.Description)
	}
	for _, permission := range item.Permissions {
		result.Permissions = append(result.Permissions, openapi.RolePermissionEntry{
			Permission: permission.Permission,
		})
	}
	return result
}

func mapUserSystemRoleBindings(items []authorizationapp.UserSystemRoleBindingView) []openapi.UserSystemRoleBinding {
	result := make([]openapi.UserSystemRoleBinding, 0, len(items))
	for _, item := range items {
		result = append(result, openapi.UserSystemRoleBinding{
			ID:              item.ID,
			UserID:          item.UserID,
			RoleID:          item.RoleID,
			RoleName:        item.RoleName,
			RoleDisplayName: item.RoleDisplayName,
			AssignedAt:      item.AssignedAt,
		})
	}
	return result
}

func mapResourceRole(item authorizationapp.ResourceRoleView) openapi.ResourceRoleInfo {
	result := openapi.ResourceRoleInfo{
		ID:          item.ID,
		Name:        item.Name,
		DisplayName: item.DisplayName,
		Color:       item.Color,
		IsSupremo:   item.IsSupremo,
	}
	if item.Description != "" {
		result.Description.SetTo(item.Description)
	}
	return result
}

func mapResourceMember(item authorizationapp.ResourceMemberView) openapi.ResourceMember {
	result := openapi.ResourceMember{
		ID:              item.ID,
		ResourceType:    mapResourceType(item.ResourceType),
		ResourceID:      item.ResourceID,
		UserID:          item.UserID,
		RoleID:          item.RoleID,
		CreatedAt:       item.CreatedAt,
		UpdatedAt:       item.UpdatedAt,
		UserEmail:       item.UserEmail,
		RoleName:        item.RoleName,
		RoleDisplayName: item.RoleDisplayName,
		RoleColor:       item.RoleColor,
		RoleIsSupremo:   item.RoleIsSupremo,
	}
	if item.UserFullName != "" {
		result.UserFullName.SetTo(item.UserFullName)
	}
	return result
}

func optStringPtr(value string, ok bool) *string {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}

func requireRoleReplacementPermission(ctx context.Context) (*accessapp.Claims, error) {
	claims, err := requireAnyPermission(ctx, "roles:write")
	if err == nil {
		return claims, nil
	}
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	if slices.Contains(claims.Permissions, "role:assign:all") && slices.Contains(claims.Permissions, "role:revoke:all") {
		return claims, nil
	}
	return nil, accessapp.ErrForbidden
}

func (h *Handlers) requireResourcePermission(ctx context.Context, resourceType string, rawResourceID string, permissions ...string) (uuid.UUID, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return uuid.Nil, accessapp.ErrUnauthorized
	}
	if h == nil || h.resolveResourceAccess == nil {
		return uuid.Nil, ogenhttp.ErrNotImplemented
	}

	resourceID, err := uuid.Parse(rawResourceID)
	if err != nil {
		return uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}

	effective, err := h.resolveResourceAccess.Execute(ctx, claims.PrincipalID, resourceType, resourceID)
	if err != nil {
		return uuid.Nil, err
	}
	for _, permission := range permissions {
		if slices.Contains(effective, permission) {
			return resourceID, nil
		}
	}
	return uuid.Nil, accessapp.ErrForbidden
}

func parseMembershipIDs(rawResourceID string, rawUserID string, rawRoleID string) (resourceID uuid.UUID, userID uuid.UUID, roleID uuid.UUID, err error) {
	resourceID, err = uuid.Parse(rawResourceID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	userID, err = uuid.Parse(rawUserID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	if rawRoleID == "" {
		return resourceID, userID, uuid.Nil, nil
	}
	roleID, err = uuid.Parse(rawRoleID)
	if err != nil {
		return uuid.Nil, uuid.Nil, uuid.Nil, authorizationapp.ErrInvalidResourceInput
	}
	return resourceID, userID, roleID, nil
}

func mapResourceType(resourceType string) openapi.ResourceMemberResourceType {
	switch resourceType {
	case authorizationdomain.ResourceTypeProject:
		return openapi.ResourceMemberResourceTypeProject
	default:
		return openapi.ResourceMemberResourceTypeDataset
	}
}

func requireAnyPermission(ctx context.Context, permissions ...string) (*accessapp.Claims, error) {
	claims, ok := authctx.ClaimsFromContext(ctx)
	if !ok {
		return nil, accessapp.ErrUnauthorized
	}
	if len(permissions) == 0 {
		return claims, nil
	}
	for _, permission := range permissions {
		if slices.Contains(claims.Permissions, permission) {
			return claims, nil
		}
	}
	return nil, accessapp.ErrForbidden
}
