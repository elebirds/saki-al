package repo

import (
	"context"
	"errors"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type CreateUserParams struct {
	PrincipalID   uuid.UUID
	Email         string
	Username      *string
	FullName      *string
	AvatarAssetID *uuid.UUID
}

type UpdateUserProfileParams = CreateUserParams

type UserRepo struct {
	q *sqlcdb.Queries
}

func NewUserRepo(pool *pgxpool.Pool) *UserRepo {
	return &UserRepo{q: sqlcdb.New(pool)}
}

func (r *UserRepo) Create(ctx context.Context, params CreateUserParams) (*identitydomain.User, error) {
	row, err := r.q.CreateIamUser(ctx, sqlcdb.CreateIamUserParams{
		PrincipalID:   params.PrincipalID,
		Email:         params.Email,
		Username:      toText(params.Username),
		FullName:      toText(params.FullName),
		AvatarAssetID: toUUID(params.AvatarAssetID),
	})
	if err != nil {
		return nil, err
	}
	return mapUser(row), nil
}

func (r *UserRepo) GetByPrincipalID(ctx context.Context, principalID uuid.UUID) (*identitydomain.User, error) {
	row, err := r.q.GetIamUserByPrincipalID(ctx, principalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapUser(row), nil
}

func (r *UserRepo) UpdateProfile(ctx context.Context, params UpdateUserProfileParams) error {
	return r.q.UpdateIamUserProfile(ctx, sqlcdb.UpdateIamUserProfileParams{
		PrincipalID:   params.PrincipalID,
		Email:         params.Email,
		Username:      toText(params.Username),
		FullName:      toText(params.FullName),
		AvatarAssetID: toUUID(params.AvatarAssetID),
	})
}

func mapUser(row sqlcdb.IamUser) *identitydomain.User {
	return &identitydomain.User{
		PrincipalID:   row.PrincipalID,
		Email:         row.Email,
		Username:      fromText(row.Username),
		FullName:      fromText(row.FullName),
		AvatarAssetID: fromUUID(row.AvatarAssetID),
		State:         identitydomain.UserState(row.State),
		CreatedAt:     row.CreatedAt.Time,
		UpdatedAt:     row.UpdatedAt.Time,
	}
}

func toText(value *string) pgtype.Text {
	if value == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *value, Valid: true}
}

func fromText(value pgtype.Text) *string {
	if !value.Valid {
		return nil
	}
	copy := value.String
	return &copy
}

func toUUID(value *uuid.UUID) pgtype.UUID {
	if value == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *value, Valid: true}
}

func fromUUID(value pgtype.UUID) *uuid.UUID {
	if !value.Valid {
		return nil
	}
	copy := uuid.UUID(value.Bytes)
	return &copy
}
