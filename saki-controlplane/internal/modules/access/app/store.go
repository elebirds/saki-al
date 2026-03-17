package app

import (
	"context"

	accessdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/access/domain"
	"github.com/google/uuid"
)

type BootstrapPrincipalSpec struct {
	UserID      string
	DisplayName string
	Permissions []string
}

type Store interface {
	GetPrincipalByUserID(ctx context.Context, userID string) (*accessdomain.Principal, error)
	GetPrincipalByID(ctx context.Context, principalID uuid.UUID) (*accessdomain.Principal, error)
	ListPermissions(ctx context.Context, principalID uuid.UUID) ([]string, error)
	UpsertBootstrapPrincipal(ctx context.Context, spec BootstrapPrincipalSpec) (*accessdomain.Principal, error)
}
