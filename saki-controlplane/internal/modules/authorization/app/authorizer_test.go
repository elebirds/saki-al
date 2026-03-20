package app

import (
	"context"
	"slices"
	"testing"

	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
)

func TestAuthorizerResolvesSystemBindingsAndResourceMemberships(t *testing.T) {
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000111")
	projectID := uuid.MustParse("00000000-0000-0000-0000-000000000222")
	otherProjectID := uuid.MustParse("00000000-0000-0000-0000-000000000333")
	systemRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000444")
	memberRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000555")
	otherRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000666")

	store := &fakeAuthorizerStore{
		systemBindings: []authorizationdomain.SystemBinding{
			{PrincipalID: principalID, RoleID: systemRoleID, SystemName: "controlplane"},
		},
		memberships: []authorizationdomain.ResourceMembership{
			{PrincipalID: principalID, RoleID: memberRoleID, ResourceType: authorizationdomain.ResourceTypeProject, ResourceID: projectID},
			{PrincipalID: principalID, RoleID: otherRoleID, ResourceType: authorizationdomain.ResourceTypeProject, ResourceID: otherProjectID},
		},
		rolePermissions: map[uuid.UUID][]string{
			systemRoleID: {"system:write", "projects:write", "unknown:permission"},
			memberRoleID: {"projects:read", "projects:write", "projects:read"},
			otherRoleID:  {"datasets:read"},
		},
	}

	authorizer := NewAuthorizer(store)
	permissions, err := authorizer.ResolvePermissions(context.Background(), principalID, authorizationdomain.ResourceRef{
		Type: authorizationdomain.ResourceTypeProject,
		ID:   projectID,
	})
	if err != nil {
		t.Fatalf("resolve permissions: %v", err)
	}

	expected := []string{"projects:read", "projects:write", "system:write"}
	if !slices.Equal(permissions, expected) {
		t.Fatalf("permissions got %v want %v", permissions, expected)
	}
}

func TestAuthorizerResolvesMigrationPermissionSnapshot(t *testing.T) {
	principalID := uuid.MustParse("00000000-0000-0000-0000-000000000777")
	systemRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000778")
	projectRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000779")
	datasetRoleID := uuid.MustParse("00000000-0000-0000-0000-000000000780")

	store := &fakeAuthorizerStore{
		systemBindings: []authorizationdomain.SystemBinding{
			{PrincipalID: principalID, RoleID: systemRoleID, SystemName: authorizationdomain.SystemNameControlplane},
		},
		memberships: []authorizationdomain.ResourceMembership{
			{
				PrincipalID:  principalID,
				RoleID:       projectRoleID,
				ResourceType: authorizationdomain.ResourceTypeProject,
				ResourceID:   uuid.MustParse("00000000-0000-0000-0000-000000000781"),
			},
			{
				PrincipalID:  principalID,
				RoleID:       datasetRoleID,
				ResourceType: authorizationdomain.ResourceTypeDataset,
				ResourceID:   uuid.MustParse("00000000-0000-0000-0000-000000000782"),
			},
		},
		rolePermissions: map[uuid.UUID][]string{
			systemRoleID:  {"system:write", "projects:write"},
			projectRoleID: {"projects:read", "projects:write"},
			datasetRoleID: {"datasets:read"},
		},
	}

	authorizer := NewAuthorizer(store)
	permissions, err := authorizer.ResolvePermissionSnapshot(context.Background(), principalID)
	if err != nil {
		t.Fatalf("resolve permission snapshot: %v", err)
	}

	expected := []string{"datasets:read", "projects:read", "projects:write", "system:write"}
	if !slices.Equal(permissions, expected) {
		t.Fatalf("permissions got %v want %v", permissions, expected)
	}
}

type fakeAuthorizerStore struct {
	systemBindings  []authorizationdomain.SystemBinding
	memberships     []authorizationdomain.ResourceMembership
	rolePermissions map[uuid.UUID][]string
}

func (s *fakeAuthorizerStore) ListSystemBindingsByPrincipal(_ context.Context, principalID uuid.UUID) ([]authorizationdomain.SystemBinding, error) {
	var result []authorizationdomain.SystemBinding
	for _, binding := range s.systemBindings {
		if binding.PrincipalID == principalID {
			result = append(result, binding)
		}
	}
	return result, nil
}

func (s *fakeAuthorizerStore) ListMembershipsByPrincipal(_ context.Context, principalID uuid.UUID) ([]authorizationdomain.ResourceMembership, error) {
	var result []authorizationdomain.ResourceMembership
	for _, membership := range s.memberships {
		if membership.PrincipalID == principalID {
			result = append(result, membership)
		}
	}
	return result, nil
}

func (s *fakeAuthorizerStore) ListRolePermissions(_ context.Context, roleID uuid.UUID) ([]string, error) {
	return append([]string(nil), s.rolePermissions[roleID]...), nil
}
