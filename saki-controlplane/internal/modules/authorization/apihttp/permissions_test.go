package apihttp

import (
	"context"
	"testing"

	authctx "github.com/elebirds/saki/saki-controlplane/internal/app/auth"
	openapi "github.com/elebirds/saki/saki-controlplane/internal/gen/openapi"
	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	authorizationapp "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/app"
	"github.com/google/uuid"
)

type fakeResolveResourceAccessExecutor struct {
	permissions []string
	err         error
}

func (f fakeResolveResourceAccessExecutor) Execute(context.Context, uuid.UUID, string, uuid.UUID) ([]string, error) {
	return f.permissions, f.err
}

type fakeGetCurrentResourcePermissionsExecutor struct {
	called       bool
	principalID  uuid.UUID
	resourceType string
	resourceID   uuid.UUID
}

func (f *fakeGetCurrentResourcePermissionsExecutor) Execute(_ context.Context, principalID uuid.UUID, resourceType string, resourceID uuid.UUID) (*authorizationapp.ResourcePermissionsView, error) {
	f.called = true
	f.principalID = principalID
	f.resourceType = resourceType
	f.resourceID = resourceID
	return &authorizationapp.ResourcePermissionsView{}, nil
}

func TestGetCurrentResourcePermissionsAllowsEmptyPermissionSnapshot(t *testing.T) {
	principalID := uuid.New()
	resourceID := uuid.New()
	executor := &fakeGetCurrentResourcePermissionsExecutor{}
	handlers := NewHandlers(HandlersDeps{
		GetCurrentResourcePermissions: executor,
		ResolveResourceAccess: fakeResolveResourceAccessExecutor{
			permissions: nil,
		},
	})

	ctx := authctx.WithClaims(context.Background(), &accessapp.Claims{
		PrincipalID: principalID,
	})
	resp, err := handlers.GetCurrentResourcePermissions(ctx, openapi.GetCurrentResourcePermissionsParams{
		ResourceType: openapi.GetCurrentResourcePermissionsResourceTypeDataset,
		ResourceID:   resourceID.String(),
	})
	if err != nil {
		t.Fatalf("GetCurrentResourcePermissions returned error: %v", err)
	}
	if resp == nil {
		t.Fatal("expected non-nil response")
	}
	if !executor.called {
		t.Fatal("expected current resource permissions executor to be called")
	}
	if executor.principalID != principalID {
		t.Fatalf("unexpected principal id: %s", executor.principalID)
	}
	if executor.resourceType != "dataset" {
		t.Fatalf("unexpected resource type: %s", executor.resourceType)
	}
	if executor.resourceID != resourceID {
		t.Fatalf("unexpected resource id: %s", executor.resourceID)
	}
}
