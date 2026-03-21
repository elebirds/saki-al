package domain

import "slices"

type ResourceRoleDefinition struct {
	ResourceType string
	Name         string
	DisplayName  string
	Description  string
	Color        string
	SortOrder    int
	IsSupremo    bool
	Assignable   bool
	Permissions  []string
}

// 关键设计：resource role catalog 由代码维护真值，而不是把“资源类型适用范围”留给数据库自由组合。
// 原先 saki-api 的一个核心问题，就是 resource role 只有名字前缀约定，没有显式的 resource_type 约束，
// 最终导致 project/dataset 角色可以被错误复用、available-roles 只能靠字符串前缀猜。
//
// 这里改成“代码目录 + 数据库存镜像”的模式：
// 1. 代码定义哪些内建角色存在、适用于哪类资源、是否可被分配；
// 2. 数据库只保存这些角色的稳定 ID 与权限映射，便于 membership 外键引用；
// 3. members API 在写入时必须回到这份目录做校验，拒绝 scope 对但 resource_type 错的角色。
var resourceRoleCatalog = map[string][]ResourceRoleDefinition{
	ResourceTypeDataset: {
		{
			ResourceType: ResourceTypeDataset,
			Name:         "dataset_owner",
			DisplayName:  "Dataset Owner",
			Description:  "Builtin dataset owner with full dataset control.",
			Color:        "gold",
			SortOrder:    0,
			IsSupremo:    true,
			Assignable:   false,
			Permissions:  []string{"datasets:read", "datasets:write", "datasets:members:write"},
		},
		{
			ResourceType: ResourceTypeDataset,
			Name:         "dataset_manager",
			DisplayName:  "Dataset Manager",
			Description:  "Can manage dataset content and membership.",
			Color:        "cyan",
			SortOrder:    10,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"datasets:read", "datasets:write", "datasets:members:write"},
		},
		{
			ResourceType: ResourceTypeDataset,
			Name:         "dataset_contributor",
			DisplayName:  "Dataset Contributor",
			Description:  "Can edit dataset content but cannot manage members.",
			Color:        "blue",
			SortOrder:    20,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"datasets:read", "datasets:write"},
		},
		{
			ResourceType: ResourceTypeDataset,
			Name:         "dataset_viewer",
			DisplayName:  "Dataset Viewer",
			Description:  "Read-only dataset access.",
			Color:        "default",
			SortOrder:    30,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"datasets:read"},
		},
	},
	ResourceTypeProject: {
		{
			ResourceType: ResourceTypeProject,
			Name:         "project_owner",
			DisplayName:  "Project Owner",
			Description:  "Builtin project owner with full project control.",
			Color:        "gold",
			SortOrder:    0,
			IsSupremo:    true,
			Assignable:   false,
			Permissions:  []string{"projects:read", "projects:write", "projects:members:write"},
		},
		{
			ResourceType: ResourceTypeProject,
			Name:         "project_manager",
			DisplayName:  "Project Manager",
			Description:  "Can manage project workflows and membership.",
			Color:        "cyan",
			SortOrder:    10,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"projects:read", "projects:write", "projects:members:write"},
		},
		{
			ResourceType: ResourceTypeProject,
			Name:         "project_contributor",
			DisplayName:  "Project Contributor",
			Description:  "Can work inside the project but cannot manage members.",
			Color:        "blue",
			SortOrder:    20,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"projects:read", "projects:write"},
		},
		{
			ResourceType: ResourceTypeProject,
			Name:         "project_viewer",
			DisplayName:  "Project Viewer",
			Description:  "Read-only project access.",
			Color:        "default",
			SortOrder:    30,
			IsSupremo:    false,
			Assignable:   true,
			Permissions:  []string{"projects:read"},
		},
	},
}

func KnownResourceTypes() []string {
	return []string{
		ResourceTypeDataset,
		ResourceTypeProject,
	}
}

func IsKnownResourceType(resourceType string) bool {
	_, ok := resourceRoleCatalog[resourceType]
	return ok
}

func ResourceRoleDefinitions(resourceType string) []ResourceRoleDefinition {
	definitions := resourceRoleCatalog[resourceType]
	result := make([]ResourceRoleDefinition, 0, len(definitions))
	for _, definition := range definitions {
		copy := definition
		copy.Permissions = append([]string(nil), definition.Permissions...)
		result = append(result, copy)
	}
	return result
}

func AssignableResourceRoleDefinitions(resourceType string) []ResourceRoleDefinition {
	definitions := ResourceRoleDefinitions(resourceType)
	result := make([]ResourceRoleDefinition, 0, len(definitions))
	for _, definition := range definitions {
		if definition.Assignable {
			result = append(result, definition)
		}
	}
	return result
}

func ResourceRoleDefinitionByName(resourceType string, name string) (ResourceRoleDefinition, bool) {
	for _, definition := range resourceRoleCatalog[resourceType] {
		if definition.Name == name {
			copy := definition
			copy.Permissions = append([]string(nil), definition.Permissions...)
			return copy, true
		}
	}
	return ResourceRoleDefinition{}, false
}

func IsAssignableResourceRole(resourceType string, roleName string) bool {
	definition, ok := ResourceRoleDefinitionByName(resourceType, roleName)
	return ok && definition.Assignable
}

func IsOwnerResourceRole(resourceType string, roleName string) bool {
	definition, ok := ResourceRoleDefinitionByName(resourceType, roleName)
	return ok && definition.IsSupremo && !definition.Assignable && slices.Contains(definition.Permissions, resourceMemberWritePermission(resourceType))
}

func ResourceReadPermission(resourceType string) string {
	switch resourceType {
	case ResourceTypeProject:
		return "projects:read"
	default:
		return "datasets:read"
	}
}

func ResourceWritePermission(resourceType string) string {
	switch resourceType {
	case ResourceTypeProject:
		return "projects:write"
	default:
		return "datasets:write"
	}
}

func ResourceMemberWritePermission(resourceType string) string {
	switch resourceType {
	case ResourceTypeProject:
		return "projects:members:write"
	default:
		return "datasets:members:write"
	}
}

func resourceMemberWritePermission(resourceType string) string {
	return ResourceMemberWritePermission(resourceType)
}
