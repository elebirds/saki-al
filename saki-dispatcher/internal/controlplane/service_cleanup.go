package controlplane

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) maybeCleanupPredictionRows(ctx context.Context) {
	if s.predictionTTLDays <= 0 {
		return
	}
	now := time.Now().UTC()
	if !s.lastTTLCleanupAt.IsZero() && now.Sub(s.lastTTLCleanupAt) < s.ttlCleanupInterval {
		return
	}
	s.lastTTLCleanupAt = now

	cutoff := now.AddDate(0, 0, -s.predictionTTLDays)
	candidateRows, eventRows, metricRows, err := s.cleanupPredictionRows(ctx, cutoff, s.predictionTTLKeepRounds)
	if err != nil {
		s.logger.Warn().Err(err).Time("cutoff", cutoff).Msg("cleanup prediction rows failed")
		return
	}
	if candidateRows == 0 && eventRows == 0 && metricRows == 0 {
		return
	}
	s.logger.Info().
		Int64("candidate_rows", candidateRows).
		Int64("event_rows", eventRows).
		Int64("metric_rows", metricRows).
		Int("ttl_days", s.predictionTTLDays).
		Int("keep_rounds", s.predictionTTLKeepRounds).
		Msg("cleanup prediction rows completed")
}

func (s *Service) cleanupPredictionRows(ctx context.Context, cutoff time.Time, keepRounds int) (int64, int64, int64, error) {
	if keepRounds < 0 {
		keepRounds = 0
	}
	tx, err := s.beginTx(ctx)
	if err != nil {
		return 0, 0, 0, err
	}
	defer tx.Rollback(ctx)

	candidateRows, err := s.deletePredictionCandidatesTx(ctx, tx, cutoff, keepRounds)
	if err != nil {
		return 0, 0, 0, err
	}
	eventRows, err := s.deletePredictionEventsTx(ctx, tx, cutoff, keepRounds)
	if err != nil {
		return 0, 0, 0, err
	}
	metricRows, err := s.deletePredictionMetricsTx(ctx, tx, cutoff, keepRounds)
	if err != nil {
		return 0, 0, 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, 0, 0, err
	}
	return candidateRows, eventRows, metricRows, nil
}

func (s *Service) deletePredictionCandidatesTx(ctx context.Context, tx pgx.Tx, cutoff time.Time, keepRounds int) (int64, error) {
	rows, err := s.qtx(tx).DeletePredictionCandidates(ctx, db.DeletePredictionCandidatesParams{
		Cutoff:     toPGTimestamp(cutoff),
		KeepRounds: int32(keepRounds),
	})
	if err != nil {
		return 0, err
	}
	return rows, nil
}

func (s *Service) deletePredictionEventsTx(ctx context.Context, tx pgx.Tx, cutoff time.Time, keepRounds int) (int64, error) {
	rows, err := s.qtx(tx).DeletePredictionEvents(ctx, db.DeletePredictionEventsParams{
		Cutoff:     toPGTimestamp(cutoff),
		KeepRounds: int32(keepRounds),
		EventTypes: []string{"metric", "progress", "log"},
	})
	if err != nil {
		return 0, err
	}
	return rows, nil
}

func (s *Service) deletePredictionMetricsTx(ctx context.Context, tx pgx.Tx, cutoff time.Time, keepRounds int) (int64, error) {
	rows, err := s.qtx(tx).DeletePredictionMetrics(ctx, db.DeletePredictionMetricsParams{
		Cutoff:     toPGTimestamp(cutoff),
		KeepRounds: int32(keepRounds),
	})
	if err != nil {
		return 0, err
	}
	return rows, nil
}
