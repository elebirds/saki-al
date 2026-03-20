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
	familyID := params.FamilyID
	if familyID == uuid.Nil {
		familyID = uuid.New()
	}
	row, err := r.q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
		PrincipalID: params.PrincipalID,
		FamilyID:    familyID,
		RotatedFrom: uuidValue(params.RotatedFrom),
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

func (r *SessionRepo) RotateRefreshSession(ctx context.Context, params identityapp.RotateRefreshSessionParams) (*identitydomain.RefreshSession, error) {
	var (
		rotated        *identitydomain.RefreshSession
		replayDetected bool
	)
	err := r.tx.InTx(ctx, func(tx pgx.Tx) error {
		q := sqlcdb.New(tx)

		currentRow, err := q.GetIamRefreshSessionByTokenHashForUpdate(ctx, params.CurrentTokenHash)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return identityapp.ErrRefreshSessionNotConsumed
			}
			return err
		}
		current := mapRefreshSession(currentRow)
		if current.IsExpired(params.Now) {
			return identityapp.ErrRefreshSessionNotConsumed
		}
		if current.ReplacedBy != nil {
			if err := q.RevokeIamRefreshSessionFamily(ctx, sqlcdb.RevokeIamRefreshSessionFamilyParams{
				Now:      timeValue(params.Now),
				FamilyID: current.FamilyID,
			}); err != nil {
				return err
			}
			replayDetected = true
			return nil
		}
		if current.IsRevoked() {
			children, err := q.CountIamRefreshSessionChildren(ctx, uuidValue(&current.ID))
			if err != nil {
				return err
			}
			if children > 0 {
				if err := q.RevokeIamRefreshSessionFamily(ctx, sqlcdb.RevokeIamRefreshSessionFamilyParams{
					Now:      timeValue(params.Now),
					FamilyID: current.FamilyID,
				}); err != nil {
					return err
				}
				replayDetected = true
				return nil
			}
			return identityapp.ErrRefreshSessionNotConsumed
		}
		if current.ReplayDetectedAt != nil {
			if err := q.RevokeIamRefreshSessionFamily(ctx, sqlcdb.RevokeIamRefreshSessionFamilyParams{
				Now:      timeValue(params.Now),
				FamilyID: current.FamilyID,
			}); err != nil {
				return err
			}
			replayDetected = true
			return nil
		}

		row, err := q.CreateIamRefreshSession(ctx, sqlcdb.CreateIamRefreshSessionParams{
			PrincipalID: current.PrincipalID,
			FamilyID:    current.FamilyID,
			RotatedFrom: uuidValue(&current.ID),
			TokenHash:   params.NewTokenHash,
			UserAgent:   textValue(params.UserAgent),
			IpAddress:   cloneRepoAddr(params.IPAddress),
			LastSeenAt:  timeValue(params.Now),
			ExpiresAt:   timeValue(params.ExpiresAt),
		})
		if err != nil {
			return err
		}

		affected, err := q.MarkIamRefreshSessionRotated(ctx, sqlcdb.MarkIamRefreshSessionRotatedParams{
			ReplacedBy: uuidValue(&row.ID),
			RevokedAt:  timeValue(params.Now),
			LastSeenAt: timeValue(params.Now),
			ID:         current.ID,
		})
		if err != nil {
			return err
		}
		if affected != 1 {
			return identityapp.ErrRefreshSessionNotConsumed
		}

		rotated = mapRefreshSession(row)
		return nil
	})
	if err != nil {
		return nil, err
	}
	if replayDetected {
		return nil, identityapp.ErrRefreshSessionReplayDetected
	}
	return rotated, nil
}

func (r *SessionRepo) RevokeRefreshSessionByTokenHash(ctx context.Context, tokenHash string, now time.Time) error {
	affected, err := r.q.RevokeIamRefreshSessionByTokenHash(ctx, sqlcdb.RevokeIamRefreshSessionByTokenHashParams{
		RevokedAt: timeValue(now),
		TokenHash: tokenHash,
	})
	if err != nil {
		return err
	}
	if affected != 1 {
		return identityapp.ErrRefreshSessionNotConsumed
	}
	return nil
}

func (r *SessionRepo) RevokeRefreshSessionsByPrincipal(ctx context.Context, principalID uuid.UUID, now time.Time) error {
	return r.q.RevokeIamRefreshSessionsByPrincipal(ctx, sqlcdb.RevokeIamRefreshSessionsByPrincipalParams{
		Now:         timeValue(now),
		PrincipalID: principalID,
	})
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
		ID:               row.ID,
		PrincipalID:      row.PrincipalID,
		FamilyID:         row.FamilyID,
		RotatedFrom:      fromUUID(row.RotatedFrom),
		ReplacedBy:       fromUUID(row.ReplacedBy),
		TokenHash:        row.TokenHash,
		UserAgent:        row.UserAgent.String,
		IPAddress:        cloneRepoAddr(row.IpAddress),
		LastSeenAt:       row.LastSeenAt.Time,
		RevokedAt:        fromTime(row.RevokedAt),
		ReplayDetectedAt: fromTime(row.ReplayDetectedAt),
		ExpiresAt:        row.ExpiresAt.Time,
		CreatedAt:        row.CreatedAt.Time,
		UpdatedAt:        row.UpdatedAt.Time,
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

func uuidValue(value *uuid.UUID) pgtype.UUID {
	if value == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *value, Valid: true}
}

func fromTime(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	copy := value.Time
	return &copy
}

func cloneRepoAddr(value *netip.Addr) *netip.Addr {
	if value == nil {
		return nil
	}
	copy := *value
	return &copy
}
