package controlplane

import (
	"context"
	"fmt"
	"strings"
	"time"

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
		statusDB := statusText
		stepPGID, err := toPGUUID(stepID)
		if err != nil {
			return err
		}
		affected, err := s.qtx(tx).UpdateStepStatusFromEvent(ctx, db.UpdateStepStatusFromEventParams{
			State:  db.Stepstatus(statusDB),
			Reason: toNullablePGText(strings.TrimSpace(event.GetStatusEvent().GetReason())),
			StepID: stepPGID,
		})
		if err != nil {
			return err
		}
		if affected == 0 {
			return fmt.Errorf("step not found: %s", stepID)
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
	statusDB := statusText

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
	affected, err := s.qtx(tx).UpdateStepResult(ctx, db.UpdateStepResultParams{
		State:        db.Stepstatus(statusDB),
		Metrics:      []byte(metricsJSON),
		Artifacts:    []byte(artifactsJSON),
		ErrorMessage: toNullablePGText(strings.TrimSpace(result.GetErrorMessage())),
		StepID:       stepPGID,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("step not found: %s", stepID)
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
