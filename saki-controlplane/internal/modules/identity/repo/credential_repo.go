package repo

import (
	"context"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type CredentialRepo struct {
	q *sqlcdb.Queries
}

func NewCredentialRepo(pool *pgxpool.Pool) *CredentialRepo {
	return &CredentialRepo{q: sqlcdb.New(pool)}
}

func (r *CredentialRepo) CreatePasswordCredential(ctx context.Context, principalID uuid.UUID, scheme string, passwordHash string) (*identitydomain.PasswordCredential, error) {
	row, err := r.q.CreateIamPasswordCredential(ctx, sqlcdb.CreateIamPasswordCredentialParams{
		PrincipalID:  principalID,
		Scheme:       scheme,
		PasswordHash: passwordHash,
	})
	if err != nil {
		return nil, err
	}
	return mapCredential(row), nil
}

func (r *CredentialRepo) ListPasswordCredentialsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]identitydomain.PasswordCredential, error) {
	rows, err := r.q.GetIamPasswordCredentialByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	result := make([]identitydomain.PasswordCredential, 0, len(rows))
	for _, row := range rows {
		result = append(result, *mapCredential(row))
	}
	return result, nil
}

func (r *CredentialRepo) DeletePasswordCredential(ctx context.Context, principalID uuid.UUID, scheme string) error {
	return r.q.DeleteIamPasswordCredential(ctx, sqlcdb.DeleteIamPasswordCredentialParams{
		PrincipalID: principalID,
		Scheme:      scheme,
	})
}

func (r *CredentialRepo) DeletePasswordCredentialsByPrincipalExcludingScheme(ctx context.Context, principalID uuid.UUID, scheme string) error {
	return r.q.DeleteIamPasswordCredentialsByPrincipalExcludingScheme(ctx, sqlcdb.DeleteIamPasswordCredentialsByPrincipalExcludingSchemeParams{
		PrincipalID: principalID,
		Scheme:      scheme,
	})
}

func mapCredential(row sqlcdb.IamPasswordCredential) *identitydomain.PasswordCredential {
	return &identitydomain.PasswordCredential{
		ID:                 row.ID,
		PrincipalID:        row.PrincipalID,
		Provider:           identitydomain.CredentialProviderLocalPassword,
		Scheme:             row.Scheme,
		PasswordHash:       row.PasswordHash,
		MustChangePassword: row.MustChangePassword,
		PasswordChangedAt:  fromTime(row.PasswordChangedAt),
		CreatedAt:          row.CreatedAt.Time,
		UpdatedAt:          row.UpdatedAt.Time,
	}
}
