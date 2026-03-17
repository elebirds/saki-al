package repo

import (
	"context"

	accessapp "github.com/elebirds/saki/saki-controlplane/internal/modules/access/app"
	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	"github.com/google/uuid"
)

type AppStore struct {
	repo *PrincipalRepo
}

var _ accessapp.Store = (*AppStore)(nil)

func NewAppStore(repo *PrincipalRepo) *AppStore {
	return &AppStore{repo: repo}
}

func (s *AppStore) GetPrincipalByUserID(ctx context.Context, userID string) (*accessdomain.Principal, error) {
	principal, err := s.repo.GetBySubjectKey(ctx, accessdomain.SubjectTypeUser, userID)
	if err != nil || principal == nil {
		return nil, err
	}
	return mapAppPrincipal(principal), nil
}

func (s *AppStore) GetPrincipalByID(ctx context.Context, principalID uuid.UUID) (*accessdomain.Principal, error) {
	principal, err := s.repo.GetByID(ctx, principalID)
	if err != nil || principal == nil {
		return nil, err
	}
	return mapAppPrincipal(principal), nil
}

func (s *AppStore) ListPermissions(ctx context.Context, principalID uuid.UUID) ([]string, error) {
	return s.repo.ListPermissions(ctx, principalID)
}

func (s *AppStore) UpsertBootstrapPrincipal(ctx context.Context, spec accessapp.BootstrapPrincipalSpec) (*accessdomain.Principal, error) {
	principal, err := s.repo.UpsertBootstrapPrincipal(ctx, UpsertBootstrapPrincipalParams{
		SubjectType: accessdomain.SubjectTypeUser,
		SubjectKey:  spec.UserID,
		DisplayName: spec.DisplayName,
		Permissions: spec.Permissions,
	})
	if err != nil || principal == nil {
		return nil, err
	}
	return mapAppPrincipal(principal), nil
}

func mapAppPrincipal(principal *Principal) *accessdomain.Principal {
	if principal == nil {
		return nil
	}
	return &accessdomain.Principal{
		ID:          principal.ID,
		SubjectType: principal.SubjectType,
		SubjectKey:  principal.SubjectKey,
		DisplayName: principal.DisplayName,
		Status:      accessdomain.PrincipalStatus(principal.Status),
	}
}
