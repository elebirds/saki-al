package apihttp

import (
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
)

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
			PrincipalID:     item.PrincipalID,
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

func mapResourceRoleDefinition(item authorizationapp.ResourceRoleDefinitionView) openapi.ResourceRoleDefinition {
	return openapi.ResourceRoleDefinition{
		ResourceType: mapResourceRoleDefinitionType(item.ResourceType),
		Name:         item.Name,
		DisplayName:  item.DisplayName,
		Description:  item.Description,
		Color:        item.Color,
		SortOrder:    int32(item.SortOrder),
		IsSupremo:    item.IsSupremo,
		Assignable:   item.Assignable,
		Permissions:  authorizationdomain.CanonicalPermissions(item.Permissions),
	}
}

func mapResourceMember(item authorizationapp.ResourceMemberView) openapi.ResourceMember {
	result := openapi.ResourceMember{
		ID:              item.ID,
		ResourceType:    mapResourceType(item.ResourceType),
		ResourceID:      item.ResourceID,
		PrincipalID:     item.PrincipalID,
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

func mapResourceType(resourceType string) openapi.ResourceMemberResourceType {
	switch resourceType {
	case authorizationdomain.ResourceTypeProject:
		return openapi.ResourceMemberResourceTypeProject
	default:
		return openapi.ResourceMemberResourceTypeDataset
	}
}

func mapResourceRoleDefinitionType(resourceType string) openapi.ResourceRoleDefinitionResourceType {
	switch resourceType {
	case authorizationdomain.ResourceTypeProject:
		return openapi.ResourceRoleDefinitionResourceTypeProject
	default:
		return openapi.ResourceRoleDefinitionResourceTypeDataset
	}
}

func optStringPtr(value string, ok bool) *string {
	if !ok {
		return nil
	}
	copy := value
	return &copy
}
