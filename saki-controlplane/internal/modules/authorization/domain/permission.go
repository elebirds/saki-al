package domain

import (
	"maps"
	"slices"
)

// 关键设计：权限目录由代码定义，而不是任由数据库自由扩展，
// 因为权限名必须保持稳定、可测试、可审计，策略判断也需要一个可预测的 allowlist。
var permissionCatalog = map[string]struct{}{
	"assets:read":       {},
	"assets:write":      {},
	"datasets:read":     {},
	"datasets:write":    {},
	"imports:read":      {},
	"imports:write":     {},
	"permissions:read":  {},
	"permissions:write": {},
	"projects:read":     {},
	"projects:write":    {},
	"roles:read":        {},
	"roles:write":       {},
	"system:read":       {},
	"system:write":      {},
	"users:read":        {},
	"users:write":       {},
}

var permissionAliases = map[string]string{
	"system_setting:read":   "system:read",
	"system_setting:update": "system:write",
}

func CanonicalPermission(permission string) string {
	if canonical, ok := permissionAliases[permission]; ok {
		return canonical
	}
	return permission
}

func IsKnownPermission(permission string) bool {
	_, ok := permissionCatalog[CanonicalPermission(permission)]
	return ok
}

func KnownPermissions() []string {
	return slices.Sorted(maps.Keys(permissionCatalog))
}
