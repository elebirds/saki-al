package apihttp

import (
	"context"

	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	"github.com/google/uuid"
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

type GetCurrentResourcePermissionsExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) (*authorizationapp.ResourcePermissionsView, error)
}

type ResolveEffectiveResourcePermissionsExecutor interface {
	Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) ([]string, error)
}

type HandlersDeps struct {
	ListRoles                     ListRolesExecutor
	PermissionCatalog             PermissionCatalogExecutor
	UserSystemRoles               UserSystemRolesExecutor
	CreateRole                    CreateRoleExecutor
	GetRole                       GetRoleExecutor
	UpdateRole                    UpdateRoleExecutor
	DeleteRole                    DeleteRoleExecutor
	ReplaceUserRoles              ReplaceUserSystemRolesExecutor
	ListResourceMembers           ListResourceMembersExecutor
	UpsertResourceMember          UpsertResourceMemberExecutor
	DeleteResourceMember          DeleteResourceMemberExecutor
	ListAssignableRoles           ListAssignableResourceRolesExecutor
	GetCurrentResourcePermissions GetCurrentResourcePermissionsExecutor
	ResolveResourceAccess         ResolveEffectiveResourcePermissionsExecutor
}

type Handlers struct {
	listRoles                     ListRolesExecutor
	permissionCatalog             PermissionCatalogExecutor
	userSystemRoles               UserSystemRolesExecutor
	createRole                    CreateRoleExecutor
	getRole                       GetRoleExecutor
	updateRole                    UpdateRoleExecutor
	deleteRole                    DeleteRoleExecutor
	replaceUserRoles              ReplaceUserSystemRolesExecutor
	listResourceMembersEx         ListResourceMembersExecutor
	upsertResourceMember          UpsertResourceMemberExecutor
	deleteResourceMember          DeleteResourceMemberExecutor
	listAssignableRoles           ListAssignableResourceRolesExecutor
	getCurrentResourcePermissions GetCurrentResourcePermissionsExecutor
	resolveResourceAccess         ResolveEffectiveResourcePermissionsExecutor
}

func NewHandlers(deps HandlersDeps) *Handlers {
	return &Handlers{
		listRoles:                     deps.ListRoles,
		permissionCatalog:             deps.PermissionCatalog,
		userSystemRoles:               deps.UserSystemRoles,
		createRole:                    deps.CreateRole,
		getRole:                       deps.GetRole,
		updateRole:                    deps.UpdateRole,
		deleteRole:                    deps.DeleteRole,
		replaceUserRoles:              deps.ReplaceUserRoles,
		listResourceMembersEx:         deps.ListResourceMembers,
		upsertResourceMember:          deps.UpsertResourceMember,
		deleteResourceMember:          deps.DeleteResourceMember,
		listAssignableRoles:           deps.ListAssignableRoles,
		getCurrentResourcePermissions: deps.GetCurrentResourcePermissions,
		resolveResourceAccess:         deps.ResolveResourceAccess,
	}
}
