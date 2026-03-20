package repo

import (
	"context"
	"errors"
	"net/netip"
	"time"

	appdb "github.com/elebirds/saki/saki-controlplane/internal/app/db"
	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	identityapp "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/app"
	identitydomain "github.com/elebirds/saki/saki-controlplane/internal/modules/identity/domain"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type SessionRepo struct {
	q  *sqlcdb.Queries
	tx *appdb.TxRunner
}

var _ identityapp.RefreshSessionStore = (*SessionRepo)(nil)

func NewSessionRepo(pool *pgxpool.Pool) *SessionRepo {
	return &SessionRepo{
		q:  sqlcdb.New(pool),
		tx: appdb.NewTxRunner(pool),
	}
}

func (r *SessionRepo) CreateRefreshSession(ctx context.Context, params identityapp.CreateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	row, err := r.q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
		PrincipalID: params.PrincipalID,
		TokenHash:   params.TokenHash,
		UserAgent:   textValue(params.UserAgent),
		IpAddress:   cloneRepoAddr(params.IPAddress),
		LastSeenAt:  timeValue(params.LastSeenAt),
		ExpiresAt:   timeValue(params.ExpiresAt),
	})
	if err != nil {
		return nil, err
	}
	return mapRefreshSession(row), nil
}

func (r *SessionRepo) GetRefreshSessionByTokenHash(ctx context.Context, tokenHash string) (*identitydomain.RefreshSession, error) {
	row, err := r.q.GetIamRefreshSessionByTokenHash(ctx, tokenHash)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapRefreshSession(row), nil
}

func (r *SessionRepo) DeleteRefreshSession(ctx context.Context, id uuid.UUID) error {
	return r.q.DeleteIamRefreshSession(ctx, id)
}

func (r *SessionRepo) RotateRefreshSession(ctx context.Context, params identityapp.RotateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	var rotated *identitydomain.RefreshSession
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		consumed, err := q.ConsumeActiveIamRefreshSessionByTokenHash(ctx, sqlcdb.ConsumeActiveIamRefreshSessionByTokenHashParams{
			TokenHash: params.CurrentTokenHash,
			Now:       timeValue(params.Now),
		})
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return identityapp.ErrRefreshSessionNotConsumed
			}
			return err
		}

		row, err := q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
			PrincipalID: consumed.PrincipalID,
			TokenHash:   params.NewTokenHash,
			UserAgent:   textValue(params.UserAgent),
			IpAddress:   cloneRepoAddr(params.IPAddress),
			LastSeenAt:  timeValue(params.Now),
			ExpiresAt:   timeValue(params.ExpiresAt),
		})
		if err != nil {
			return err
		}

		rotated = mapRefreshSession(row)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return rotated, nil
}

func (r *SessionRepo) ListRefreshSessionsByPrincipal(ctx context.Context, principalID uuid.UUID) ([]identitydomain.RefreshSession, error) {
	rows, err := r.q.ListIamRefreshSessionsByPrincipal(ctx, principalID)
	if err != nil {
		return nil, err
	}

	result := make([]identitydomain.RefreshSession, 0, len(rows))
	for _, row := range rows {
		result = append(result, *mapRefreshSession(row))
	}
	return result, nil
}

func mapRefreshSession(row sqlcdb.IamRefreshSession) *identitydomain.RefreshSession {
	return &identitydomain.RefreshSession{
		ID:          row.ID,
		PrincipalID: row.PrincipalID,
		TokenHash:   row.TokenHash,
		UserAgent:   row.UserAgent.String,
		IPAddress:   cloneRepoAddr(row.IpAddress),
		LastSeenAt:  row.LastSeenAt.Time,
		ExpiresAt:   row.ExpiresAt.Time,
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}

func textValue(value string) pgtype.Text {
	if value == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: value, Valid: true}
}

func timeValue(value time.Time) pgtype.Timestamptz {
	if value.IsZero() {
		return pgtype.Timestamptz{}
	}
	return pgtype.Timestamptz{Time: value, Valid: true}
}

func cloneRepoAddr(value *netip.Addr) *netip.Addr {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}
