package controlplane

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) OnStepEvent(ctx context.Context, event *runtimecontrolv1.StepEvent) error {
	if !s.dbEnabled() || event == nil {
		return nil
	}
	stepID := strings.TrimSpace(event.GetStepId())
	if stepID == "" {
		return nil
	}

	eventType, eventPayload, statusText := decodeStepEvent(event)
	if eventType == "" {
		return nil
	}
	payloadJSON, err := marshalJSON(eventPayload)
	if err != nil {
		return err
	}
	eventTS := stepEventTime(event.GetTs())

	tx, err := s.beginTx(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if inserted, err := s.insertStepEventTx(
		ctx,
		tx,
		stepID,
		event.GetSeq(),
		eventTS,
		eventType,
		payloadJSON,
		strings.TrimSpace(event.GetRequestId()),
	); err != nil {
		return err
	} else if !inserted {
		// Duplicate event by (step_id, seq), skip side effects.
		return tx.Commit(ctx)
	}

	switch eventType {
	case "status":
		stepPGID, err := toPGUUID(stepID)
		if err != nil {
			return err
		}
		targetState := db.Stepstatus(statusText)
		affected, err := s.updateStepStatusFromEventGuardedTx(
			ctx,
			tx,
			stepPGID,
			targetState,
			strings.TrimSpace(event.GetStatusEvent().GetReason()),
		)
		if err != nil {
			return err
		}
		if affected == 0 {
			return fmt.Errorf("invalid step transition from runtime event: step=%s target=%s", stepID, targetState)
		}

	case "metric":
		metricPayload := event.GetMetricEvent()
		if metricPayload != nil {
			if err := s.insertMetricPointsTx(
				ctx,
				tx,
				stepID,
				int(metricPayload.GetStep()),
				ptrInt(int(metricPayload.GetEpoch())),
				metricPayload.GetMetrics(),
				eventTS,
			); err != nil {
				return err
			}
		}

	case "artifact":
		artifactPayload := event.GetArtifactEvent()
		if artifactPayload != nil {
			if err := s.mergeArtifactIntoStepTx(ctx, tx, stepID, artifactPayload.GetArtifact()); err != nil {
				return err
			}
		}
	}

	roundID, err := s.findRoundIDByStep(ctx, tx, stepID)
	if err != nil {
		return err
	}
	if roundID != "" {
		if _, err := s.refreshRoundAggregateTx(ctx, tx, roundID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Service) OnStepResult(ctx context.Context, result *runtimecontrolv1.StepResult) error {
	if !s.dbEnabled() || result == nil {
		return nil
	}
	stepID := strings.TrimSpace(result.GetStepId())
	if stepID == "" {
		return nil
	}
	statusText := runtimeStatusToStepStatus(result.GetStatus())
	if statusText == "" {
		statusText = stepFailed
	}
	targetState := db.Stepstatus(statusText)

	metricsJSON, err := marshalJSON(result.GetMetrics())
	if err != nil {
		return err
	}
	artifactsJSON, err := marshalArtifacts(result.GetArtifacts())
	if err != nil {
		return err
	}

	tx, err := s.beginTx(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return err
	}
	affected, err := s.updateStepResultGuardedTx(ctx, tx, stepPGID, targetState, []byte(metricsJSON), []byte(artifactsJSON), strings.TrimSpace(result.GetErrorMessage()))
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("invalid step result transition: step=%s target=%s", stepID, targetState)
	}

	if err := s.replaceStepCandidatesTx(ctx, tx, stepID, result.GetCandidates()); err != nil {
		return err
	}
	if err := s.insertMetricPointsTx(ctx, tx, stepID, 0, nil, result.GetMetrics(), time.Now().UTC()); err != nil {
		return err
	}

	roundID, err := s.findRoundIDByStep(ctx, tx, stepID)
	if err != nil {
		return err
	}
	if roundID != "" {
		if _, err := s.refreshRoundAggregateTx(ctx, tx, roundID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Service) updateStepStatusFromEventGuardedTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID pgtype.UUID,
	target db.Stepstatus,
	reason string,
) (int64, error) {
	for _, fromState := range stepFromCandidatesForTarget(target) {
		if !canStepTransition(fromState, target) {
			continue
		}
		affected, err := s.qtx(tx).UpdateStepStatusFromEventGuarded(ctx, db.UpdateStepStatusFromEventGuardedParams{
			State:     target,
			Reason:    toNullablePGText(reason),
			StepID:    stepID,
			FromState: fromState,
		})
		if err != nil {
			return 0, err
		}
		if affected > 0 {
			return affected, nil
		}
	}
	current, err := s.qtx(tx).GetStepStateForUpdate(ctx, stepID)
	if err != nil {
		return 0, err
	}
	if current == target {
		return 1, nil
	}
	return 0, nil
}

func (s *Service) updateStepResultGuardedTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID pgtype.UUID,
	target db.Stepstatus,
	metrics []byte,
	artifacts []byte,
	errorMessage string,
) (int64, error) {
	for _, fromState := range stepFromCandidatesForTarget(target) {
		if !canStepTransition(fromState, target) {
			continue
		}
		affected, err := s.qtx(tx).UpdateStepResultGuarded(ctx, db.UpdateStepResultGuardedParams{
			State:        target,
			Metrics:      metrics,
			Artifacts:    artifacts,
			ErrorMessage: toNullablePGText(errorMessage),
			StepID:       stepID,
			FromState:    fromState,
		})
		if err != nil {
			return 0, err
		}
		if affected > 0 {
			return affected, nil
		}
	}
	current, err := s.qtx(tx).GetStepStateForUpdate(ctx, stepID)
	if err != nil {
		return 0, err
	}
	if current == target {
		return 1, nil
	}
	return 0, nil
}
