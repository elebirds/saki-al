package repo

import (
	"context"
	"errors"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	AssetUploadIntentStateInitiated = "initiated"
	AssetUploadIntentStateCompleted = "completed"
	AssetUploadIntentStateCanceled  = "canceled"
	AssetUploadIntentStateExpired   = "expired"
)

type AssetUploadIntent struct {
	ID                  uuid.UUID
	AssetID             uuid.UUID
	OwnerType           string
	OwnerID             uuid.UUID
	Role                string
	IsPrimary           bool
	DeclaredContentType string
	State               string
	IdempotencyKey      string
	ExpiresAt           time.Time
	CreatedBy           *uuid.UUID
	CompletedAt         *time.Time
	CanceledAt          *time.Time
	CreatedAt           time.Time
	UpdatedAt           time.Time
}

type CreateAssetUploadIntentParams struct {
	AssetID             uuid.UUID
	OwnerType           string
	OwnerID             uuid.UUID
	Role                string
	IsPrimary           bool
	DeclaredContentType string
	IdempotencyKey      string
	ExpiresAt           time.Time
	CreatedBy           *uuid.UUID
}

type GetAssetUploadIntentByOwnerKeyParams struct {
	OwnerType      string
	OwnerID        uuid.UUID
	Role           string
	IdempotencyKey string
}

type MarkAssetUploadIntentCompletedParams struct {
	AssetID     uuid.UUID
	CompletedAt time.Time
}

type MarkAssetUploadIntentCanceledParams struct {
	AssetID    uuid.UUID
	CanceledAt time.Time
}

type MarkAssetUploadIntentExpiredParams struct {
	AssetID   uuid.UUID
	ExpiredAt time.Time
}

type AssetUploadIntentRepo struct {
	q *sqlcdb.Queries
}

func NewAssetUploadIntentRepo(pool *pgxpool.Pool) *AssetUploadIntentRepo {
	return newAssetUploadIntentRepo(sqlcdb.New(pool))
}

func newAssetUploadIntentRepo(q *sqlcdb.Queries) *AssetUploadIntentRepo {
	return &AssetUploadIntentRepo{q: q}
}

func (r *AssetUploadIntentRepo) Create(ctx context.Context, params CreateAssetUploadIntentParams) (*AssetUploadIntent, error) {
	row, err := r.q.CreateAssetUploadIntent(ctx, sqlcdb.CreateAssetUploadIntentParams{
		AssetID:             params.AssetID,
		OwnerType:           sqlcdb.AssetOwnerType(params.OwnerType),
		OwnerID:             params.OwnerID,
		Role:                sqlcdb.AssetReferenceRole(params.Role),
		IsPrimary:           params.IsPrimary,
		DeclaredContentType: params.DeclaredContentType,
		IdempotencyKey:      params.IdempotencyKey,
		ExpiresAt:           pgTime(params.ExpiresAt),
		CreatedBy:           uuidToPgtype(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func (r *AssetUploadIntentRepo) GetByAssetID(ctx context.Context, assetID uuid.UUID) (*AssetUploadIntent, error) {
	row, err := r.q.GetAssetUploadIntentByAssetID(ctx, assetID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func (r *AssetUploadIntentRepo) GetByOwnerKey(ctx context.Context, params GetAssetUploadIntentByOwnerKeyParams) (*AssetUploadIntent, error) {
	row, err := r.q.GetAssetUploadIntentByOwnerKey(ctx, sqlcdb.GetAssetUploadIntentByOwnerKeyParams{
		OwnerType:      sqlcdb.AssetOwnerType(params.OwnerType),
		OwnerID:        params.OwnerID,
		Role:           sqlcdb.AssetReferenceRole(params.Role),
		IdempotencyKey: params.IdempotencyKey,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func (r *AssetUploadIntentRepo) MarkCompleted(ctx context.Context, params MarkAssetUploadIntentCompletedParams) (*AssetUploadIntent, error) {
	row, err := r.q.MarkAssetUploadIntentCompleted(ctx, sqlcdb.MarkAssetUploadIntentCompletedParams{
		AssetID:     params.AssetID,
		CompletedAt: pgTime(params.CompletedAt),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func (r *AssetUploadIntentRepo) MarkCanceled(ctx context.Context, params MarkAssetUploadIntentCanceledParams) (*AssetUploadIntent, error) {
	row, err := r.q.MarkAssetUploadIntentCanceled(ctx, sqlcdb.MarkAssetUploadIntentCanceledParams{
		AssetID:    params.AssetID,
		CanceledAt: pgTime(params.CanceledAt),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func (r *AssetUploadIntentRepo) MarkExpired(ctx context.Context, params MarkAssetUploadIntentExpiredParams) (*AssetUploadIntent, error) {
	row, err := r.q.MarkAssetUploadIntentExpired(ctx, sqlcdb.MarkAssetUploadIntentExpiredParams{
		AssetID:   params.AssetID,
		ExpiredAt: pgTime(params.ExpiredAt),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAssetUploadIntent(row), nil
}

func fromSQLCAssetUploadIntent(row sqlcdb.AssetUploadIntent) *AssetUploadIntent {
	return &AssetUploadIntent{
		ID:                  row.ID,
		AssetID:             row.AssetID,
		OwnerType:           string(row.OwnerType),
		OwnerID:             row.OwnerID,
		Role:                string(row.Role),
		IsPrimary:           row.IsPrimary,
		DeclaredContentType: row.DeclaredContentType,
		State:               string(row.State),
		IdempotencyKey:      row.IdempotencyKey,
		ExpiresAt:           row.ExpiresAt.Time,
		CreatedBy:           pgUUIDToUUIDPtr(row.CreatedBy),
		CompletedAt:         pgTimestamptzToTimePtr(row.CompletedAt),
		CanceledAt:          pgTimestamptzToTimePtr(row.CanceledAt),
		CreatedAt:           row.CreatedAt.Time,
		UpdatedAt:           row.UpdatedAt.Time,
	}
}
