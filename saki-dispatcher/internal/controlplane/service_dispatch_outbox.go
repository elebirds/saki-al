package controlplane

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) dispatchOutboxBatch(ctx context.Context, limit int) (int, error) {
	if !s.dbEnabled() {
		return 0, nil
	}
	rows, err := s.queries.ClaimDispatchOutboxDue(ctx, int32(max(1, limit)))
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, row := range rows {
		outboxPGID, err := toPGUUID(row.ID)
		if err != nil {
			continue
		}

		payload := &runtimecontrolv1.StepPayload{}
		if err := protojson.Unmarshal(row.Payload, payload); err != nil {
			nextAt := toPGTimestamp(time.Now().UTC().Add(dispatchOutboxRetryBackoff(row.AttemptCount)))
			_, retryErr := s.queries.MarkDispatchOutboxRetry(ctx, db.MarkDispatchOutboxRetryParams{
				NextAttemptAt: nextAt,
				LastError:     toNullablePGText(fmt.Sprintf("invalid outbox payload: %v", err)),
				OutboxID:      outboxPGID,
			})
			if retryErr != nil {
				return sent, retryErr
			}
			continue
		}

		if s.dispatcher.DispatchStep(row.ExecutorID, row.RequestID, payload) {
			affected, err := s.queries.MarkDispatchOutboxSent(ctx, outboxPGID)
			if err != nil {
				return sent, err
			}
			if affected > 0 {
				sent++
			}
			continue
		}

		nextAt := toPGTimestamp(time.Now().UTC().Add(dispatchOutboxRetryBackoff(row.AttemptCount)))
		_, err = s.queries.MarkDispatchOutboxRetry(ctx, db.MarkDispatchOutboxRetryParams{
			NextAttemptAt: nextAt,
			LastError:     toNullablePGText("executor unavailable or queue full"),
			OutboxID:      outboxPGID,
		})
		if err != nil {
			return sent, err
		}
	}
	return sent, nil
}

func (s *Service) recoverDispatchOutbox(ctx context.Context, limit int) error {
	if !s.dbEnabled() {
		return nil
	}
	staleSendingCutoff := toPGTimestamp(time.Now().UTC().Add(-30 * time.Second))
	if _, err := s.queries.ReleaseStaleSendingOutbox(ctx, staleSendingCutoff); err != nil {
		return err
	}

	orphanCutoff := toPGTimestamp(time.Now().UTC().Add(-2 * time.Minute))
	stepIDs, err := s.queries.ListOrphanDispatchingStepIDs(ctx, db.ListOrphanDispatchingStepIDsParams{
		Cutoff:     orphanCutoff,
		LimitCount: int32(max(1, limit)),
	})
	if err != nil {
		return err
	}
	for _, stepID := range stepIDs {
		stepPGID, err := toPGUUID(stepID)
		if err != nil {
			continue
		}
		_, err = s.queries.RecoverStaleDispatchingStepToReady(ctx, db.RecoverStaleDispatchingStepToReadyParams{
			LastError: toPGText("dispatch outbox orphan recovered"),
			StepID:    stepPGID,
		})
		if err != nil {
			return err
		}
	}

	cleanupCutoff := toPGTimestamp(time.Now().UTC().Add(-24 * time.Hour))
	if _, err := s.queries.DeleteSentDispatchOutboxBefore(ctx, cleanupCutoff); err != nil {
		return err
	}
	return nil
}

func dispatchOutboxRetryBackoff(attempt int32) time.Duration {
	if attempt <= 1 {
		return time.Second
	}
	seconds := 1 << minInt(6, int(attempt)-1)
	if seconds > 60 {
		seconds = 60
	}
	return time.Duration(seconds) * time.Second
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
