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

type PreviewManifest struct {
	Token           string
	Mode            string
	ProjectID       uuid.UUID
	UploadSessionID uuid.UUID
	Manifest        []byte
	ParamsHash      string
	ExpiresAt       time.Time
	CreatedAt       time.Time
}

type PutPreviewManifestParams struct {
	Token           string
	Mode            string
	ProjectID       uuid.UUID
	UploadSessionID uuid.UUID
	Manifest        []byte
	ParamsHash      string
	ExpiresAt       time.Time
}

type PreviewRepo struct {
	q *sqlcdb.Queries
}

func NewPreviewRepo(pool *pgxpool.Pool) *PreviewRepo {
	return &PreviewRepo{q: sqlcdb.New(pool)}
}

func (r *PreviewRepo) Put(ctx context.Context, params PutPreviewManifestParams) (*PreviewManifest, error) {
	row, err := r.q.PutImportPreviewManifest(ctx, sqlcdb.PutImportPreviewManifestParams{
		Token:           params.Token,
		Mode:            params.Mode,
		ProjectID:       params.ProjectID,
		UploadSessionID: params.UploadSessionID,
		Manifest:        params.Manifest,
		ParamsHash:      params.ParamsHash,
		ExpiresAt:       pgtypeTimestamptz(params.ExpiresAt),
	})
	if err != nil {
		return nil, err
	}
	return &PreviewManifest{
		Token:           row.Token,
		Mode:            row.Mode,
		ProjectID:       row.ProjectID,
		UploadSessionID: row.UploadSessionID,
		Manifest:        row.Manifest,
		ParamsHash:      row.ParamsHash,
		ExpiresAt:       row.ExpiresAt.Time,
		CreatedAt:       row.CreatedAt.Time,
	}, nil
}

func (r *PreviewRepo) Get(ctx context.Context, token string) (*PreviewManifest, error) {
	row, err := r.q.GetImportPreviewManifest(ctx, token)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return &PreviewManifest{
		Token:           row.Token,
		Mode:            row.Mode,
		ProjectID:       row.ProjectID,
		UploadSessionID: row.UploadSessionID,
		Manifest:        row.Manifest,
		ParamsHash:      row.ParamsHash,
		ExpiresAt:       row.ExpiresAt.Time,
		CreatedAt:       row.CreatedAt.Time,
	}, nil
}
