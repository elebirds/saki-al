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
	{Name: "datasets:members:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "datasets:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "imports:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "imports:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "permissions:read", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "permissions:write", AllowedFor: []RoleScopeKind{RoleScopeSystem}},
	{Name: "projects:read", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
	{Name: "projects:members:write", AllowedFor: []RoleScopeKind{RoleScopeSystem, RoleScopeResource}},
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

func CanonicalPermission(permission string) string {
	return permission
}

func IsKnownPermission(permission string) bool {
	_, ok := permissionCatalogIndex[permission]
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

// 关键设计：public API 只暴露并持有一套 canonical permission。
// 这里保留该函数只是为了集中完成去重与排序，不再承担旧权限别名归一化职责。
func CanonicalPermissions(permissions []string) []string {
	normalized := make(map[string]struct{}, len(permissions))
	for _, permission := range permissions {
		normalized[permission] = struct{}{}
	}

	result := make([]string, 0, len(normalized))
	for permission := range normalized {
		result = append(result, permission)
	}
	slices.Sort(result)
	return result
}
