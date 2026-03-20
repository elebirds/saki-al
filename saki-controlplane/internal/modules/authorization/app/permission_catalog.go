package app

import (
	"context"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
)

type PermissionCatalogUseCase struct{}

func NewPermissionCatalogUseCase() *PermissionCatalogUseCase {
	return &PermissionCatalogUseCase{}
}

func (u *PermissionCatalogUseCase) Execute(context.Context) (*PermissionCatalog, error) {
	return &PermissionCatalog{
		AllPermissions:      authorizationdomain.KnownPermissions(),
		SystemPermissions:   authorizationdomain.PermissionsForRoleScope(authorizationdomain.RoleScopeSystem),
		ResourcePermissions: authorizationdomain.PermissionsForRoleScope(authorizationdomain.RoleScopeResource),
	}, nil
}
