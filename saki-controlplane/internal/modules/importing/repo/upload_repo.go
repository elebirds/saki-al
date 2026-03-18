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

type UploadSession struct {
	ID          uuid.UUID
	UserID      uuid.UUID
	Mode        string
	FileName    string
	ObjectKey   string
	ContentType string
	Status      string
	CompletedAt *time.Time
	AbortedAt   *time.Time
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

type InitUploadSessionParams struct {
	UserID      uuid.UUID
	Mode        string
	FileName    string
	ObjectKey   string
	ContentType string
}

type UploadRepo struct {
	q *sqlcdb.Queries
}

func NewUploadRepo(pool *pgxpool.Pool) *UploadRepo {
	return &UploadRepo{q: sqlcdb.New(pool)}
}

func (r *UploadRepo) Init(ctx context.Context, params InitUploadSessionParams) (*UploadSession, error) {
	row, err := r.q.CreateImportUploadSession(ctx, sqlcdb.CreateImportUploadSessionParams{
		UserID:      params.UserID,
		Mode:        params.Mode,
		FileName:    params.FileName,
		ObjectKey:   params.ObjectKey,
		ContentType: params.ContentType,
	})
	if err != nil {
		return nil, err
	}
	return mapUploadSession(row), nil
}

func (r *UploadRepo) Get(ctx context.Context, id uuid.UUID) (*UploadSession, error) {
	row, err := r.q.GetImportUploadSession(ctx, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return mapUploadSession(row), nil
}

func (r *UploadRepo) MarkCompleted(ctx context.Context, id uuid.UUID) (*UploadSession, error) {
	row, err := r.q.CompleteImportUploadSession(ctx, id)
	if err != nil {
		return nil, err
	}
	return mapUploadSession(row), nil
}

func (r *UploadRepo) Abort(ctx context.Context, id uuid.UUID) (*UploadSession, error) {
	row, err := r.q.AbortImportUploadSession(ctx, id)
	if err != nil {
		return nil, err
	}
	return mapUploadSession(row), nil
}

func mapUploadSession(row sqlcdb.ImportUploadSession) *UploadSession {
	return &UploadSession{
		ID:          row.ID,
		UserID:      row.UserID,
		Mode:        row.Mode,
		FileName:    row.FileName,
		ObjectKey:   row.ObjectKey,
		ContentType: row.ContentType,
		Status:      string(row.Status),
		CompletedAt: optionalTime(row.CompletedAt),
		AbortedAt:   optionalTime(row.AbortedAt),
		CreatedAt:   row.CreatedAt.Time,
		UpdatedAt:   row.UpdatedAt.Time,
	}
}
