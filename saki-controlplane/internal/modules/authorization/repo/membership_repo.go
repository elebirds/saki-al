package repo

import (
	"context"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	authorizationdomain "github.com/elebirds/saki/saki-controlplane/internal/modules/authorization/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type MembershipRepo struct {
	q *sqlcdb.Queries
}

func NewMembershipRepo(pool *pgxpool.Pool) *MembershipRepo {
	return &MembershipRepo{q: sqlcdb.New(pool)}
}

func (r *MembershipRepo) ListByPrincipal(ctx context.Context, principalID uuid.UUID) ([]authorizationdomain.ResourceMembership, error) {
	rows, err := r.q.ListAuthzMembershipsByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	result := make([]authorizationdomain.ResourceMembership, 0, len(rows))
	for _, row := range rows {
		result = append(result, mapMembership(row))
	}
	return result, nil
}

func (r *MembershipRepo) ListByResource(ctx context.Context, ref authorizationdomain.ResourceRef) ([]authorizationdomain.ResourceMembership, error) {
	rows, err := r.q.ListAuthzResourceMemberships(ctx, sqlcdb.ListAuthzResourceMembershipsParams{
		ResourceType: ref.Type,
		ResourceID:   ref.ID,
	})
	if err != nil {
		return nil, err
	}

	result := make([]authorizationdomain.ResourceMembership, 0, len(rows))
	for _, row := range rows {
		result = append(result, mapMembership(row))
	}
	return result, nil
}

func (r *MembershipRepo) Upsert(ctx context.Context, principalID uuid.UUID, roleID uuid.UUID, ref authorizationdomain.ResourceRef) (*authorizationdomain.ResourceMembership, error) {
	row, err := r.q.UpsertAuthzResourceMembership(ctx, sqlcdb.UpsertAuthzResourceMembershipParams{
		PrincipalID:  principalID,
		RoleID:       roleID,
		ResourceType: ref.Type,
		ResourceID:   ref.ID,
	})
	if err != nil {
		return nil, err
	}
	membership := mapMembership(row)
	return &membership, nil
}

func (r *MembershipRepo) Delete(ctx context.Context, id uuid.UUID) error {
	return r.q.DeleteAuthzResourceMembership(ctx, id)
}

func mapMembership(row sqlcdb.AuthzResourceMembership) authorizationdomain.ResourceMembership {
	return authorizationdomain.ResourceMembership{
		ID:           row.ID,
		PrincipalID:  row.PrincipalID,
		RoleID:       row.RoleID,
		ResourceType: row.ResourceType,
		ResourceID:   row.ResourceID,
		CreatedAt:    row.CreatedAt.Time,
		UpdatedAt:    row.UpdatedAt.Time,
	}
}
