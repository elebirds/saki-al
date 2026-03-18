package repo

import (
	"context"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const AssetReferenceLifecycleDurable = "durable"

type AssetReference struct {
	ID        uuid.UUID
	AssetID   uuid.UUID
	OwnerType string
	OwnerID   uuid.UUID
	Role      string
	Lifecycle string
	IsPrimary bool
	Metadata  []byte
	CreatedBy *uuid.UUID
	CreatedAt time.Time
	DeletedAt *time.Time
}

type CreateAssetReferenceParams struct {
	AssetID   uuid.UUID
	OwnerType string
	OwnerID   uuid.UUID
	Role      string
	Lifecycle string
	IsPrimary bool
	Metadata  []byte
	CreatedBy *uuid.UUID
}

type ListActiveReferencesByOwnerParams struct {
	OwnerType string
	OwnerID   uuid.UUID
}

type InvalidateAssetReferencesForOwnerParams struct {
	OwnerType string
	OwnerID   uuid.UUID
	DeletedAt time.Time
}

type AssetReferenceRepo struct {
	q *sqlcdb.Queries
}

func NewAssetReferenceRepo(pool *pgxpool.Pool) *AssetReferenceRepo {
	return newAssetReferenceRepo(sqlcdb.New(pool))
}

func newAssetReferenceRepo(q *sqlcdb.Queries) *AssetReferenceRepo {
	return &AssetReferenceRepo{q: q}
}

func (r *AssetReferenceRepo) CreateDurable(ctx context.Context, params CreateAssetReferenceParams) (*AssetReference, error) {
	row, err := r.q.CreateDurableReference(ctx, sqlcdb.CreateDurableReferenceParams{
		AssetID:   params.AssetID,
		OwnerType: sqlcdb.AssetOwnerType(params.OwnerType),
		OwnerID:   params.OwnerID,
		Role:      sqlcdb.AssetReferenceRole(params.Role),
		Lifecycle: sqlcdb.AssetReferenceLifecycle(params.Lifecycle),
		IsPrimary: params.IsPrimary,
		Metadata:  normalizeMetadata(params.Metadata),
		CreatedBy: uuidToPgtype(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromCreateDurableReferenceRow(row), nil
}

func (r *AssetReferenceRepo) ListActiveByOwner(ctx context.Context, params ListActiveReferencesByOwnerParams) ([]AssetReference, error) {
	rows, err := r.q.ListActiveReferencesByOwner(ctx, sqlcdb.ListActiveReferencesByOwnerParams{
		OwnerType: sqlcdb.AssetOwnerType(params.OwnerType),
		OwnerID:   params.OwnerID,
	})
	if err != nil {
		return nil, err
	}

	references := make([]AssetReference, 0, len(rows))
	for _, row := range rows {
		references = append(references, *fromSQLCAssetReference(row))
	}
	return references, nil
}

func (r *AssetReferenceRepo) CountActiveForAsset(ctx context.Context, assetID uuid.UUID) (int64, error) {
	return r.q.CountActiveReferencesForAsset(ctx, assetID)
}

func (r *AssetReferenceRepo) InvalidateForOwner(ctx context.Context, params InvalidateAssetReferencesForOwnerParams) (int64, error) {
	return r.q.InvalidateAssetReferencesForOwner(ctx, sqlcdb.InvalidateAssetReferencesForOwnerParams{
		OwnerType: sqlcdb.AssetOwnerType(params.OwnerType),
		OwnerID:   params.OwnerID,
		DeletedAt: pgTime(params.DeletedAt),
	})
}

func fromSQLCAssetReference(row sqlcdb.AssetReference) *AssetReference {
	return newAssetReferenceFromFields(
		row.ID,
		row.AssetID,
		row.OwnerType,
		row.OwnerID,
		row.Role,
		row.Lifecycle,
		row.IsPrimary,
		row.Metadata,
		row.CreatedBy,
		row.CreatedAt,
		row.DeletedAt,
	)
}

func fromCreateDurableReferenceRow(row sqlcdb.CreateDurableReferenceRow) *AssetReference {
	return newAssetReferenceFromFields(
		row.ID,
		row.AssetID,
		row.OwnerType,
		row.OwnerID,
		row.Role,
		row.Lifecycle,
		row.IsPrimary,
		row.Metadata,
		row.CreatedBy,
		row.CreatedAt,
		row.DeletedAt,
	)
}

func newAssetReferenceFromFields(
	id uuid.UUID,
	assetID uuid.UUID,
	ownerType sqlcdb.AssetOwnerType,
	ownerID uuid.UUID,
	role sqlcdb.AssetReferenceRole,
	lifecycle sqlcdb.AssetReferenceLifecycle,
	isPrimary bool,
	metadata []byte,
	createdBy pgtype.UUID,
	createdAt pgtype.Timestamptz,
	deletedAt pgtype.Timestamptz,
) *AssetReference {
	return &AssetReference{
		ID:        id,
		AssetID:   assetID,
		OwnerType: string(ownerType),
		OwnerID:   ownerID,
		Role:      string(role),
		Lifecycle: string(lifecycle),
		IsPrimary: isPrimary,
		Metadata:  metadata,
		CreatedBy: pgUUIDToUUIDPtr(createdBy),
		CreatedAt: createdAt.Time,
		DeletedAt: pgTimestamptzToTimePtr(deletedAt),
	}
}
