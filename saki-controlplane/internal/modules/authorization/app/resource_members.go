package app

import (
	"context"
	"time"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

type ResourceRoleView struct {
	ID          string
	Name        string
	DisplayName string
	Description string
	Color       string
	IsSupremo   bool
}

type ResourceMemberView struct {
	ID              string
	ResourceType    string
	ResourceID      string
	UserID          string
	RoleID          string
	CreatedAt       time.Time
	UpdatedAt       time.Time
	UserEmail       string
	UserFullName    string
	RoleName        string
	RoleDisplayName string
	RoleColor       string
	RoleIsSupremo   bool
}

type ResourcePermissionsView struct {
	ResourceRole *ResourceRoleView
	Permissions  []string
	IsOwner      bool
}

type ResourceMembershipStore interface {
	ListResourceMembers(ctx context.Context, ref authorizationdomain.ResourceRef) ([]ResourceMemberView, error)
	UpsertResourceMember(ctx context.Context, principalID uuid.UUID, roleID uuid.UUID, ref authorizationdomain.ResourceRef) (*ResourceMemberView, error)
	DeleteResourceMember(ctx context.Context, principalID uuid.UUID, ref authorizationdomain.ResourceRef) error
	ListAssignableResourceRoles(ctx context.Context, ref authorizationdomain.ResourceRef) ([]ResourceRoleView, error)
	GetResourceRole(ctx context.Context, principalID uuid.UUID, ref authorizationdomain.ResourceRef) (*ResourceRoleView, error)
}

type EffectiveResourcePermissionResolver interface {
	ResolvePermissions(ctx context.Context, principalID uuid.UUID, resource authorizationdomain.ResourceRef) ([]string, error)
}

type ListResourceMembersUseCase struct {
	store ResourceMembershipStore
}

func NewListResourceMembersUseCase(store ResourceMembershipStore) *ListResourceMembersUseCase {
	return &ListResourceMembersUseCase{store: store}
}

func (u *ListResourceMembersUseCase) Execute(ctx context.Context, resourceType string, resourceID uuid.UUID) ([]ResourceMemberView, error) {
	ref, err := newResourceRef(resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	return u.store.ListResourceMembers(ctx, ref)
}

type UpsertResourceMemberCommand struct {
	ResourceType string
	ResourceID   uuid.UUID
	UserID       uuid.UUID
	RoleID       uuid.UUID
}

type UpsertResourceMemberUseCase struct {
	store ResourceMembershipStore
}

func NewUpsertResourceMemberUseCase(store ResourceMembershipStore) *UpsertResourceMemberUseCase {
	return &UpsertResourceMemberUseCase{store: store}
}

func (u *UpsertResourceMemberUseCase) Execute(ctx context.Context, cmd UpsertResourceMemberCommand) (*ResourceMemberView, error) {
	ref, err := newResourceRef(cmd.ResourceType, cmd.ResourceID)
	if err != nil {
		return nil, err
	}
	if cmd.UserID == uuid.Nil || cmd.RoleID == uuid.Nil {
		return nil, ErrInvalidResourceInput
	}
	return u.store.UpsertResourceMember(ctx, cmd.UserID, cmd.RoleID, ref)
}

type DeleteResourceMemberUseCase struct {
	store ResourceMembershipStore
}

func NewDeleteResourceMemberUseCase(store ResourceMembershipStore) *DeleteResourceMemberUseCase {
	return &DeleteResourceMemberUseCase{store: store}
}

func (u *DeleteResourceMemberUseCase) Execute(ctx context.Context, resourceType string, resourceID uuid.UUID, principalID uuid.UUID) error {
	ref, err := newResourceRef(resourceType, resourceID)
	if err != nil {
		return err
	}
	if principalID == uuid.Nil {
		return ErrInvalidResourceInput
	}
	return u.store.DeleteResourceMember(ctx, principalID, ref)
}

type ListAssignableResourceRolesUseCase struct {
	store ResourceMembershipStore
}

func NewListAssignableResourceRolesUseCase(store ResourceMembershipStore) *ListAssignableResourceRolesUseCase {
	return &ListAssignableResourceRolesUseCase{store: store}
}

func (u *ListAssignableResourceRolesUseCase) Execute(ctx context.Context, resourceType string, resourceID uuid.UUID) ([]ResourceRoleView, error) {
	ref, err := newResourceRef(resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	return u.store.ListAssignableResourceRoles(ctx, ref)
}

type GetResourcePermissionsUseCase struct {
	store    ResourceMembershipStore
	resolver EffectiveResourcePermissionResolver
}

func NewGetResourcePermissionsUseCase(store ResourceMembershipStore, resolver EffectiveResourcePermissionResolver) *GetResourcePermissionsUseCase {
	return &GetResourcePermissionsUseCase{
		store:    store,
		resolver: resolver,
	}
}

func (u *GetResourcePermissionsUseCase) Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) (*ResourcePermissionsView, error) {
	if principalID == uuid.Nil {
		return nil, ErrInvalidResourceInput
	}
	ref, err := newResourceRef(resourceType, resourceID)
	if err != nil {
		return nil, err
	}

	permissions, err := u.resolver.ResolvePermissions(ctx, principalID, ref)
	if err != nil {
		return nil, err
	}
	// 关键设计：/permissions/resource 是“当前主体对该资源的能力快照”，不是资源存在性探针。
	// 因此当调用者对目标资源没有任何有效权限时，直接返回空快照而不是继续探测资源是否存在，
	// 这样普通登录用户不会因为 404/200 差异而枚举出资源是否存在。
	if len(permissions) == 0 {
		return &ResourcePermissionsView{
			Permissions: nil,
			IsOwner:     false,
		}, nil
	}

	role, err := u.store.GetResourceRole(ctx, principalID, ref)
	if err != nil {
		return nil, err
	}

	return &ResourcePermissionsView{
		ResourceRole: role,
		Permissions:  permissions,
		IsOwner:      role != nil && role.IsSupremo,
	}, nil
}

type ResolveEffectiveResourcePermissionsUseCase struct {
	resolver EffectiveResourcePermissionResolver
}

func NewResolveEffectiveResourcePermissionsUseCase(resolver EffectiveResourcePermissionResolver) *ResolveEffectiveResourcePermissionsUseCase {
	return &ResolveEffectiveResourcePermissionsUseCase{resolver: resolver}
}

func (u *ResolveEffectiveResourcePermissionsUseCase) Execute(ctx context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) ([]string, error) {
	if principalID == uuid.Nil {
		return nil, ErrInvalidResourceInput
	}
	ref, err := newResourceRef(resourceType, resourceID)
	if err != nil {
		return nil, err
	}
	return u.resolver.ResolvePermissions(ctx, principalID, ref)
}

func newResourceRef(resourceType string, resourceID uuid.UUID) (authorizationdomain.ResourceRef, error) {
	if !authorizationdomain.IsKnownResourceType(resourceType) {
		return authorizationdomain.ResourceRef{}, ErrInvalidResourceType
	}
	if resourceID == uuid.Nil {
		return authorizationdomain.ResourceRef{}, ErrInvalidResourceInput
	}
	return authorizationdomain.ResourceRef{
		Type: resourceType,
		ID:   resourceID,
	}, nil
}
