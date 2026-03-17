package effects

import (
	"context"
	"fmt"
	"time"

	"github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/app/commands"
	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
)

const (
	defaultClaimLimit   int32 = 32
	defaultClaimTTL           = 30 * time.Second
	defaultRetryBackoff       = 15 * time.Second
)

type Effect interface {
	Apply(ctx context.Context, event commands.OutboxEvent) error
}

type TopicEffect interface {
	Effect
	Topic() string
}

type OutboxStore interface {
	ClaimDue(ctx context.Context, limit int32, claimUntil time.Time) ([]runtimerepo.OutboxEntry, error)
	MarkPublished(ctx context.Context, id int64, claimAvailableAt time.Time) error
	MarkRetry(ctx context.Context, id int64, claimAvailableAt, nextAvailableAt time.Time, lastError string) error
}

type Worker struct {
	outbox       OutboxStore
	effects      map[string][]Effect
	claimLimit   int32
	claimTTL     time.Duration
	retryBackoff time.Duration
	now          func() time.Time
}

func NewWorker(outbox OutboxStore, effects ...TopicEffect) *Worker {
	byTopic := make(map[string][]Effect, len(effects))
	for _, effect := range effects {
		byTopic[effect.Topic()] = append(byTopic[effect.Topic()], effect)
	}

	return &Worker{
		outbox:       outbox,
		effects:      byTopic,
		claimLimit:   defaultClaimLimit,
		claimTTL:     defaultClaimTTL,
		retryBackoff: defaultRetryBackoff,
		now:          time.Now,
	}
}

func (w *Worker) RunOnce(ctx context.Context) error {
	claimUntil := w.now().Add(w.claimTTL)
	entries, err := w.outbox.ClaimDue(ctx, w.claimLimit, claimUntil)
	if err != nil {
		return err
	}

	for _, entry := range entries {
		if err := w.applyEffects(ctx, entry); err != nil {
			if retryErr := w.outbox.MarkRetry(ctx, entry.ID, entry.AvailableAt, w.now().Add(w.retryBackoff), err.Error()); retryErr != nil {
				return retryErr
			}
			continue
		}
		if err := w.outbox.MarkPublished(ctx, entry.ID, entry.AvailableAt); err != nil {
			return err
		}
	}

	return nil
}

func (w *Worker) applyEffects(ctx context.Context, entry runtimerepo.OutboxEntry) error {
	effects := w.effects[entry.Topic]
	if len(effects) == 0 {
		return fmt.Errorf("no effect registered for topic %s", entry.Topic)
	}

	event := commands.OutboxEvent{
		Topic:          entry.Topic,
		AggregateID:    entry.AggregateID,
		IdempotencyKey: entry.IdempotencyKey,
		Payload:        append([]byte(nil), entry.Payload...),
	}

	for _, effect := range effects {
		if err := effect.Apply(ctx, event); err != nil {
			return err
		}
	}
	return nil
}
