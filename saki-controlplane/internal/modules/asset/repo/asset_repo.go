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

type AssetRepo struct {
	q *sqlcdb.Queries
}

func NewAssetRepo(pool *pgxpool.Pool) *AssetRepo {
	return &AssetRepo{q: sqlcdb.New(pool)}
}

func (r *AssetRepo) CreatePending(ctx context.Context, params CreatePendingParams) (*Asset, error) {
	row, err := r.q.CreatePendingAsset(ctx, sqlcdb.CreatePendingAssetParams{
		Kind:           params.Kind,
		StorageBackend: params.StorageBackend,
		Bucket:         params.Bucket,
		ObjectKey:      params.ObjectKey,
		ContentType:    params.ContentType,
		Metadata:       params.Metadata,
		CreatedBy:      uuidToPgtype(params.CreatedBy),
	})
	if err != nil {
		return nil, err
	}
	return fromSQLCAsset(row), nil
}

func (r *AssetRepo) Get(ctx context.Context, id uuid.UUID) (*Asset, error) {
	row, err := r.q.GetAsset(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return fromSQLCAsset(row), nil
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
	return fromSQLCAsset(row), nil
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
	return fromSQLCAsset(row), nil
}

func fromSQLCAsset(row sqlcdb.Asset) *Asset {
	return &Asset{
		ID:             row.ID,
		Kind:           row.Kind,
		Status:         row.Status,
		StorageBackend: row.StorageBackend,
		Bucket:         row.Bucket,
		ObjectKey:      row.ObjectKey,
		ContentType:    row.ContentType,
		SizeBytes:      row.SizeBytes,
		Sha256Hex:      pgTextToStringPtr(row.Sha256Hex),
		Metadata:       row.Metadata,
		CreatedBy:      pgUUIDToUUIDPtr(row.CreatedBy),
		CreatedAt:      row.CreatedAt.Time,
		UpdatedAt:      row.UpdatedAt.Time,
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
