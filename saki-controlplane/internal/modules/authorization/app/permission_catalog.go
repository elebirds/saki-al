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
	resourceRoles := make([]ResourceRoleDefinitionView, 0)
	// 关键设计：/permissions/resource 不再承载“当前用户快照”，
	// 它只暴露资源权限目录与内建资源角色定义，供管理端一次性读取真值。
	for _, resourceType := range authorizationdomain.KnownResourceTypes() {
		for _, definition := range authorizationdomain.ResourceRoleDefinitions(resourceType) {
			resourceRoles = append(resourceRoles, ResourceRoleDefinitionView{
				ResourceType: definition.ResourceType,
				Name:         definition.Name,
				DisplayName:  definition.DisplayName,
				Description:  definition.Description,
				Color:        definition.Color,
				SortOrder:    definition.SortOrder,
				IsSupremo:    definition.IsSupremo,
				Assignable:   definition.Assignable,
				Permissions:  append([]string(nil), definition.Permissions...),
			})
		}
	}

	return &PermissionCatalog{
		AllPermissions:      authorizationdomain.KnownPermissions(),
		SystemPermissions:   authorizationdomain.PermissionsForRoleScope(authorizationdomain.RoleScopeSystem),
		ResourcePermissions: authorizationdomain.PermissionsForRoleScope(authorizationdomain.RoleScopeResource),
		ResourceRoles:       resourceRoles,
	}, nil
}
