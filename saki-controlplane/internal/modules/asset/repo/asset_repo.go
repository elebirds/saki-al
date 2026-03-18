package repo

import (
	"context"
	"errors"
	"time"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	AssetStatusPendingUpload = "pending_upload"
	AssetStatusReady         = "ready"
)

type Asset struct {
	ID             uuid.UUID
	Kind           string
	Status         string
	StorageBackend string
	Bucket         string
	ObjectKey      string
	ContentType    string
	SizeBytes      int64
	Sha256Hex      *string
	Metadata       []byte
	CreatedBy      *uuid.UUID
	ReadyAt        *time.Time
	OrphanedAt     *time.Time
	CreatedAt      time.Time
	UpdatedAt      time.Time
}

type CreatePendingParams struct {
	Kind           string
	StorageBackend string
	Bucket         string
	ObjectKey      string
	ContentType    string
	Metadata       []byte
	CreatedBy      *uuid.UUID
}

type MarkReadyParams struct {
	ID          uuid.UUID
	SizeBytes   int64
	Sha256Hex   *string
	ContentType string
}

type ListStalePendingAssetsParams struct {
	Now    time.Time
	Cutoff time.Time
}

type ListReadyOrphanedAssetsParams struct {
	Cutoff time.Time
}

type GetReadyOrphanedAssetForUpdateParams struct {
	ID     uuid.UUID
	Cutoff time.Time
}

type AssetRepo struct {
	q *sqlcdb.Queries
}

func NewAssetRepo(pool *pgxpool.Pool) *AssetRepo {
	return newAssetRepo(sqlcdb.New(pool))
}

func newAssetRepo(q *sqlcdb.Queries) *AssetRepo {
	return &AssetRepo{q: q}
}

func (r *AssetRepo) CreatePending(ctx context.Context, params CreatePendingParams) (*Asset, error) {
	row, err := r.q.CreatePendingAsset(ctx, sqlcdb.CreatePendingAssetParams{
		Kind:           sqlcdb.AssetKind(params.Kind),
		StorageBackend: sqlcdb.AssetStorageBackend(params.StorageBackend),
		Bucket:         params.Bucket,
		ObjectKey:      params.ObjectKey,
		ContentType:    params.ContentType,
		Metadata:       normalizeMetadata(params.Metadata),
		CreatedBy:      uuidToPgtype(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromAssetRow(row), nil
}

func (r *AssetRepo) Get(ctx context.Context, id uuid.UUID) (*Asset, error) {
	row, err := r.q.GetAsset(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromAssetRow(row), nil
}

func (r *AssetRepo) GetByStorageLocation(ctx context.Context, bucket string, objectKey string) (*Asset, error) {
	row, err := r.q.GetAssetByStorageLocation(ctx, sqlcdb.GetAssetByStorageLocationParams{
		Bucket:    bucket,
		ObjectKey: objectKey,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromAssetRow(row), nil
}

func (r *AssetRepo) MarkReady(ctx context.Context, params MarkReadyParams) (*Asset, error) {
	row, err := r.q.MarkAssetReady(ctx, sqlcdb.MarkAssetReadyParams{
		ID:          params.ID,
		SizeBytes:   params.SizeBytes,
		Sha256Hex:   stringToPgtype(params.Sha256Hex),
		ContentType: params.ContentType,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromAssetRow(row), nil
}

func (r *AssetRepo) ListStalePending(ctx context.Context, params ListStalePendingAssetsParams) ([]Asset, error) {
	rows, err := r.q.ListStalePendingAssets(ctx, sqlcdb.ListStalePendingAssetsParams{
		Now:    pgTime(params.Now),
		Cutoff: pgTime(params.Cutoff),
	})
	if err != nil {
		return nil, err
	}

	assets := make([]Asset, 0, len(rows))
	for _, row := range rows {
		assets = append(assets, *fromAssetRow(row))
	}
	return assets, nil
}

func (r *AssetRepo) ListReadyOrphaned(ctx context.Context, params ListReadyOrphanedAssetsParams) ([]Asset, error) {
	rows, err := r.q.ListReadyOrphanedAssets(ctx, pgTime(params.Cutoff))
	if err != nil {
		return nil, err
	}

	assets := make([]Asset, 0, len(rows))
	for _, row := range rows {
		assets = append(assets, *fromAssetRow(row))
	}
	return assets, nil
}

func (r *AssetRepo) GetReadyOrphanedForUpdate(ctx context.Context, params GetReadyOrphanedAssetForUpdateParams) (*Asset, error) {
	row, err := r.q.GetReadyOrphanedAssetForUpdate(ctx, sqlcdb.GetReadyOrphanedAssetForUpdateParams{
		ID:     params.ID,
		Cutoff: pgTime(params.Cutoff),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromAssetRow(row), nil
}

func (r *AssetRepo) Delete(ctx context.Context, id uuid.UUID) (bool, error) {
	rows, err := r.q.DeleteAsset(ctx, id)
	if err != nil {
		return false, err
	}
	return rows > 0, nil
}

func fromAssetRow(row sqlcdb.Asset) *Asset {
	return newAssetFromFields(
		row.ID,
		row.Kind,
		row.Status,
		row.StorageBackend,
		row.Bucket,
		row.ObjectKey,
		row.ContentType,
		row.SizeBytes,
		row.Sha256Hex,
		row.Metadata,
		row.CreatedBy,
		row.ReadyAt,
		row.OrphanedAt,
		row.CreatedAt,
		row.UpdatedAt,
	)
}

func newAssetFromFields(
	id uuid.UUID,
	kind sqlcdb.AssetKind,
	status sqlcdb.AssetStatus,
	storageBackend sqlcdb.AssetStorageBackend,
	bucket string,
	objectKey string,
	contentType string,
	sizeBytes int64,
	sha256Hex pgtype.Text,
	metadata []byte,
	createdBy pgtype.UUID,
	readyAt pgtype.Timestamptz,
	orphanedAt pgtype.Timestamptz,
	createdAt pgtype.Timestamptz,
	updatedAt pgtype.Timestamptz,
) *Asset {
	return &Asset{
		ID:             id,
		Kind:           string(kind),
		Status:         string(status),
		StorageBackend: string(storageBackend),
		Bucket:         bucket,
		ObjectKey:      objectKey,
		ContentType:    contentType,
		SizeBytes:      sizeBytes,
		Sha256Hex:      pgTextToStringPtr(sha256Hex),
		Metadata:       metadata,
		CreatedBy:      pgUUIDToUUIDPtr(createdBy),
		ReadyAt:        pgTimestamptzToTimePtr(readyAt),
		OrphanedAt:     pgTimestamptzToTimePtr(orphanedAt),
		CreatedAt:      createdAt.Time,
		UpdatedAt:      updatedAt.Time,
	}
}

func uuidToPgtype(v *uuid.UUID) pgtype.UUID {
	if v == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *v, Valid: true}
}

func pgUUIDToUUIDPtr(v pgtype.UUID) *uuid.UUID {
	if !v.Valid {
		return nil
	}
	id := uuid.UUID(v.Bytes)
	return &id
}

func stringToPgtype(v *string) pgtype.Text {
	if v == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *v, Valid: true}
}

func pgTextToStringPtr(v pgtype.Text) *string {
	if !v.Valid {
		return nil
	}
	s := v.String
	return &s
}

func pgTime(v time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: v, Valid: !v.IsZero()}
}

func pgTimestamptzToTimePtr(v pgtype.Timestamptz) *time.Time {
	if !v.Valid {
		return nil
	}
	t := v.Time
	return &t
}

func normalizeMetadata(v []byte) []byte {
	if len(v) == 0 {
		return []byte(`{}`)
	}
	return v
}
