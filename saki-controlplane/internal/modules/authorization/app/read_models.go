package app

import "time"

type PermissionCatalog struct {
	AllPermissions      []string
	SystemPermissions   []string
	ResourcePermissions []string
	ResourceRoles       []ResourceRoleDefinitionView
}

type ResourceRoleDefinitionView struct {
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

type RolePermissionView struct {
	Permission string
}

type RoleView struct {
	ID          string
	Name        string
	DisplayName string
	Description string
	Type        string
	BuiltIn     bool
	Mutable     bool
	Color       string
	IsSupremo   bool
	SortOrder   int
	IsSystem    bool
	Permissions []RolePermissionView
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

type RoleListResult struct {
	Items   []RoleView
	Total   int
	Offset  int
	Limit   int
	Size    int
	HasMore bool
}

type UserSystemRoleBindingView struct {
	ID              string
	UserID          string
	RoleID          string
	RoleName        string
	RoleDisplayName string
	RoleColor       string
	RoleIsSupremo   bool
	AssignedAt      time.Time
}
