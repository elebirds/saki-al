package repo

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	sqlcdb "github.com/elebirds/saki/saki-controlplane/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
)

var ErrOutboxClaimExpired = errors.New("runtime outbox claim expired")

type OutboxEntry struct {
	ID             int64
	Topic          string
	AggregateType  string
	AggregateID    string
	IdempotencyKey string
	Payload        []byte
	AvailableAt    time.Time
	AttemptCount   int32
	CreatedAt      time.Time
	PublishedAt    *time.Time
	LastError      *string
}

type AppendOutboxParams struct {
	Topic          string
	AggregateType  string
	AggregateID    string
	IdempotencyKey string
	Payload        []byte
	AvailableAt    time.Time
}

type OutboxRepo struct {
	q *sqlcdb.Queries
}

func NewOutboxRepo(pool *pgxpool.Pool) *OutboxRepo {
	return &OutboxRepo{q: sqlcdb.New(pool)}
}

func (r *OutboxRepo) Append(ctx context.Context, params AppendOutboxParams) (*OutboxEntry, error) {
	aggregateType := outboxAggregateTypeOrDefault(params.AggregateType)
	idempotencyKey := outboxIdempotencyKey(params.Topic, aggregateType, params.AggregateID, params.Payload, params.IdempotencyKey)
	availableAt := outboxAvailableAtOrNow(params.AvailableAt)

	row, err := r.q.AppendRuntimeOutbox(ctx, sqlcdb.AppendRuntimeOutboxParams{
		Topic:          params.Topic,
		AggregateType:  aggregateType,
		AggregateID:    params.AggregateID,
		IdempotencyKey: idempotencyKey,
		Payload:        params.Payload,
		AvailableAt:    pgtype.Timestamptz{Time: availableAt, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	return runtimeOutboxFromAppendRow(row), nil
}

func (r *OutboxRepo) ClaimDue(ctx context.Context, limit int32, claimUntil time.Time) ([]OutboxEntry, error) {
	rows, err := r.q.ClaimDueRuntimeOutbox(ctx, sqlcdb.ClaimDueRuntimeOutboxParams{
		LimitCount: limit,
		ClaimUntil: pgtype.Timestamptz{Time: claimUntil, Valid: true},
	})
	if err != nil {
		return nil, err
	}

	entries := make([]OutboxEntry, 0, len(rows))
	for _, row := range rows {
		entries = append(entries, *runtimeOutboxFromClaimRow(row))
	}
	return entries, nil
}

func (r *OutboxRepo) MarkPublished(ctx context.Context, id int64, claimAvailableAt time.Time) error {
	rows, err := r.q.MarkRuntimeOutboxPublished(ctx, sqlcdb.MarkRuntimeOutboxPublishedParams{
		ID:               id,
		ClaimAvailableAt: pgtype.Timestamptz{Time: claimAvailableAt, Valid: true},
	})
	if err != nil {
		return err
	}
	if rows == 0 {
		return ErrOutboxClaimExpired
	}
	return nil
}

func (r *OutboxRepo) MarkRetry(ctx context.Context, id int64, claimAvailableAt, nextAvailableAt time.Time, lastError string) error {
	rows, err := r.q.MarkRuntimeOutboxRetry(ctx, sqlcdb.MarkRuntimeOutboxRetryParams{
		ID:               id,
		ClaimAvailableAt: pgtype.Timestamptz{Time: claimAvailableAt, Valid: true},
		NextAvailableAt:  pgtype.Timestamptz{Time: nextAvailableAt, Valid: true},
		LastError:        pgtype.Text{String: lastError, Valid: lastError != ""},
	})
	if err != nil {
		return err
	}
	if rows == 0 {
		return ErrOutboxClaimExpired
	}
	return nil
}

type CommandOutboxWriter struct {
	repo *OutboxRepo
}

func NewCommandOutboxWriter(pool *pgxpool.Pool) *CommandOutboxWriter {
	return &CommandOutboxWriter{repo: NewOutboxRepo(pool)}
}

func (w *CommandOutboxWriter) Append(ctx context.Context, event commands.OutboxEvent) error {
	_, err := w.repo.Append(ctx, AppendOutboxParams{
		Topic:          event.Topic,
		AggregateID:    event.AggregateID,
		IdempotencyKey: event.IdempotencyKey,
		Payload:        event.Payload,
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

func optionalLastError(value pgtype.Text) *string {
	if !value.Valid {
		return nil
	}
	text := value.String
	return &text
}

func runtimeOutboxFromAppendRow(row sqlcdb.AppendRuntimeOutboxRow) *OutboxEntry {
	return &OutboxEntry{
		ID:             row.ID,
		Topic:          row.Topic,
		AggregateType:  row.AggregateType,
		AggregateID:    row.AggregateID,
		IdempotencyKey: row.IdempotencyKey,
		Payload:        row.Payload,
		AvailableAt:    row.AvailableAt.Time,
		AttemptCount:   row.AttemptCount,
		CreatedAt:      row.CreatedAt.Time,
		PublishedAt:    optionalPublishedAt(row.PublishedAt),
		LastError:      optionalLastError(row.LastError),
	}
}

func runtimeOutboxFromClaimRow(row sqlcdb.ClaimDueRuntimeOutboxRow) *OutboxEntry {
	return &OutboxEntry{
		ID:             row.ID,
		Topic:          row.Topic,
		AggregateType:  row.AggregateType,
		AggregateID:    row.AggregateID,
		IdempotencyKey: row.IdempotencyKey,
		Payload:        row.Payload,
		AvailableAt:    row.AvailableAt.Time,
		AttemptCount:   row.AttemptCount,
		CreatedAt:      row.CreatedAt.Time,
		PublishedAt:    optionalPublishedAt(row.PublishedAt),
		LastError:      optionalLastError(row.LastError),
	}
}

func outboxAggregateTypeOrDefault(aggregateType string) string {
	if aggregateType == "" {
		return "task"
	}
	return aggregateType
}

func outboxIdempotencyKey(topic, aggregateType, aggregateID string, payload []byte, override string) string {
	if override != "" {
		return override
	}
	payloadHash := sha256.Sum256(payload)
	return fmt.Sprintf("%s:%s:%s:%s", topic, aggregateType, aggregateID, hex.EncodeToString(payloadHash[:8]))
}

func outboxAvailableAtOrNow(availableAt time.Time) time.Time {
	if availableAt.IsZero() {
		return time.Now()
	}
	return availableAt
}
