package repo

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

type OutboxEntry struct {
	ID          int64
	Topic       string
	AggregateID string
	Payload     []byte
	CreatedAt   time.Time
	PublishedAt *time.Time
}

type AppendOutboxParams struct {
	Topic       string
	AggregateID string
	Payload     []byte
}

type OutboxRepo struct {
	q *sqlcdb.Queries
}

func NewOutboxRepo(pool *pgxpool.Pool) *OutboxRepo {
	return &OutboxRepo{q: sqlcdb.New(pool)}
}

func (r *OutboxRepo) Append(ctx context.Context, params AppendOutboxParams) (*OutboxEntry, error) {
	row, err := r.q.AppendRuntimeOutbox(ctx, sqlcdb.AppendRuntimeOutboxParams{
		Topic:       params.Topic,
		AggregateID: params.AggregateID,
		Payload:     params.Payload,
	})
	if err != nil {
		return nil, err
	}

	return &OutboxEntry{
		ID:          row.ID,
		Topic:       row.Topic,
		AggregateID: row.AggregateID,
		Payload:     row.Payload,
		CreatedAt:   row.CreatedAt.Time,
		PublishedAt: optionalPublishedAt(row.PublishedAt),
	}, nil
}

type CommandOutboxWriter struct {
	repo *OutboxRepo
}

func NewCommandOutboxWriter(pool *pgxpool.Pool) *CommandOutboxWriter {
	return &CommandOutboxWriter{repo: NewOutboxRepo(pool)}
}

func (w *CommandOutboxWriter) Append(ctx context.Context, event commands.OutboxEvent) error {
	_, err := w.repo.Append(ctx, AppendOutboxParams{
		Topic:       event.Topic,
		AggregateID: event.AggregateID,
		Payload:     event.Payload,
	})
	return err
}

func optionalPublishedAt(value pgtype.Timestamptz) *time.Time {
	if !value.Valid {
		return nil
	}
	ts := value.Time
	return &ts
}
