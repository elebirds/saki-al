package domain

import "slices"

type PermissionDefinition struct {
	Name       string
	AllowedFor []RoleScopeKind
}

// 关键设计：权限目录由代码定义，而不是任由数据库自由扩展，
// 因为权限名必须保持稳定、可测试、可审计，策略判断也需要一个可预测的 allowlist。
//
// 同时我们在目录里显式标注“哪些权限可以分配给 system role / resource role”，
// 这样角色编辑器、服务端校验、默认角色装配都能共享同一份真值，而不是各写一套 if/else。
var permissionCatalog = []PermissionDefinition{
	{Name: "assets:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "assets:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "datasets:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "datasets:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "imports:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "imports:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "permissions:read", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "permissions:write", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "projects:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "projects:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "roles:read", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "roles:write", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "system:read", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "system:write", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "users:read", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "users:write", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
}

var permissionCatalogIndex = func() map[string]PermissionDefinition {
	index := make(map[string]PermissionDefinition, len(permissionCatalog))
	for _, definition := range permissionCatalog {
		index[definition.Name] = definition
	}
	return index
}()

var permissionAliases = map[string]string{
	"system_setting:read":   "system:read",
	"system_setting:update": "system:write",
}

var permissionTransportAliases = map[string][]string{
	"users:read": {
		"user:read:all",
		"user:list:all",
		"user:role_read:all",
	},
	"users:write": {
		"user:create:all",
		"user:update:all",
		"user:delete:all",
		"user:manage:all",
	},
	"roles:read": {
		"role:read:all",
	},
	"roles:write": {
		"role:create:all",
		"role:update:all",
		"role:delete:all",
		"role:assign:all",
		"role:revoke:all",
	},
	"system:read": {
		"system_setting:read:all",
	},
	"system:write": {
		"system_setting:update:all",
		"system:manage:all",
	},
	"projects:read": {
		"project:read:all",
		"project:read:assigned",
	},
	"projects:write": {
		"project:create:all",
		"project:update:all",
		"project:archive:all",
		"project:delete:all",
		"project:assign:all",
		"project:export:all",
		"project:update:assigned",
		"project:archive:assigned",
		"project:delete:assigned",
		"project:assign:assigned",
		"project:export:assigned",
	},
	"datasets:read": {
		"dataset:read:all",
		"dataset:read:assigned",
	},
	"datasets:write": {
		"dataset:create:all",
		"dataset:update:all",
		"dataset:delete:all",
		"dataset:assign:all",
		"dataset:link_project:all",
		"dataset:export:all",
		"dataset:import:all",
		"dataset:update:assigned",
		"dataset:assign:assigned",
		"dataset:link_project:assigned",
		"dataset:export:assigned",
		"dataset:import:assigned",
	},
}

func CanonicalPermission(permission string) string {
	if canonical, ok := permissionAliases[permission]; ok {
		return canonical
	}
	return permission
}

func IsKnownPermission(permission string) bool {
	_, ok := permissionCatalogIndex[CanonicalPermission(permission)]
	return ok
}

func KnownPermissions() []string {
	permissions := make([]string, 0, len(permissionCatalog))
	for _, definition := range permissionCatalog {
		permissions = append(permissions, definition.Name)
	}
	slices.Sort(permissions)
	return permissions
}

func PermissionsForRoleScope(scope RoleScopeKind) []string {
	permissions := make([]string, 0, len(permissionCatalog))
	for _, definition := range permissionCatalog {
		if slices.Contains(definition.AllowedFor, scope) {
			permissions = append(permissions, definition.Name)
		}
	}
	slices.Sort(permissions)
	return permissions
}

func ExpandedPermissionsForTransport(permissions []string) []string {
	expanded := make(map[string]struct{}, len(permissions))
	for _, permission := range permissions {
		canonical := CanonicalPermission(permission)
		expanded[canonical] = struct{}{}
		for _, alias := range permissionTransportAliases[canonical] {
			expanded[alias] = struct{}{}
		}
	}

	result := make([]string, 0, len(expanded))
	for permission := range expanded {
		result = append(result, permission)
	}
	slices.Sort(result)
	return result
}
