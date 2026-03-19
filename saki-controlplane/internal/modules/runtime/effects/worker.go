package effects

import (
	"context"
	"fmt"
	"time"

	runtimerepo "github.com/elebirds/saki/saki-controlplane/internal/modules/runtime/repo"
	"github.com/google/uuid"
)

const (
	defaultClaimLimit   int32 = 32
	defaultClaimTTL           = 30 * time.Second
	defaultRetryBackoff       = 15 * time.Second
)

type CommandEffect interface {
	Apply(ctx context.Context, cmd runtimerepo.AgentCommand) error
	CommandType() string
}

type AgentCommandStore interface {
	ClaimForPush(ctx context.Context, limit int32, claimUntil time.Time) ([]runtimerepo.AgentCommand, error)
	Ack(ctx context.Context, commandID, claimToken uuid.UUID, ackAt time.Time) error
	MarkFinished(ctx context.Context, commandID, claimToken uuid.UUID, finishedAt time.Time) error
	MarkRetry(ctx context.Context, commandID, claimToken uuid.UUID, nextAvailableAt time.Time, lastError string) error
}

type Worker struct {
	commands     AgentCommandStore
	effects      map[string][]CommandEffect
	claimLimit   int32
	claimTTL     time.Duration
	retryBackoff time.Duration
	now          func() time.Time
}

func NewWorker(commands AgentCommandStore, effects ...CommandEffect) *Worker {
	byCommandType := make(map[string][]CommandEffect, len(effects))
	for _, effect := range effects {
		byCommandType[effect.CommandType()] = append(byCommandType[effect.CommandType()], effect)
	}

	return &Worker{
		commands:     commands,
		effects:      byCommandType,
		claimLimit:   defaultClaimLimit,
		claimTTL:     defaultClaimTTL,
		retryBackoff: defaultRetryBackoff,
		now:          time.Now,
	}
}

func (w *Worker) RunOnce(ctx context.Context) error {
	claimUntil := w.now().Add(w.claimTTL)
	items, err := w.commands.ClaimForPush(ctx, w.claimLimit, claimUntil)
	if err != nil {
		return err
	}

	for _, item := range items {
		if item.ClaimToken == nil {
			return fmt.Errorf("claimed command %s missing claim token", item.CommandID)
		}

		if err := w.applyEffects(ctx, item); err != nil {
			if retryErr := w.commands.MarkRetry(ctx, item.CommandID, *item.ClaimToken, w.now().Add(w.retryBackoff), err.Error()); retryErr != nil {
				return retryErr
			}
			continue
		}

		finishedAt := w.now()
		if err := w.commands.Ack(ctx, item.CommandID, *item.ClaimToken, finishedAt); err != nil {
			return err
		}
		if err := w.commands.MarkFinished(ctx, item.CommandID, *item.ClaimToken, finishedAt); err != nil {
			return err
		}
	}

	return nil
}

func (w *Worker) applyEffects(ctx context.Context, cmd runtimerepo.AgentCommand) error {
	effects := w.effects[cmd.CommandType]
	if len(effects) == 0 {
		return fmt.Errorf("no effect registered for command type %s", cmd.CommandType)
	}

	for _, effect := range effects {
		if err := effect.Apply(ctx, cmd); err != nil {
			return err
		}
	}
	return nil
}
