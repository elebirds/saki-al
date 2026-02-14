package controlplane

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/rs/zerolog"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	"github.com/elebirds/saki/saki-dispatcher/internal/repo"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

const (
	statusDraft     = "DRAFT"
	statusRunning   = "RUNNING"
	statusPaused    = "PAUSED"
	statusStopping  = "STOPPING"
	statusStopped   = "STOPPED"
	statusCompleted = "COMPLETED"
	statusFailed    = "FAILED"

	phaseALTrain          = "AL_TRAIN"
	phaseALScore          = "AL_SCORE"
	phaseALSelect         = "AL_SELECT"
	phaseALWaitAnnotation = "AL_WAIT_USER"
	phaseALEval           = "AL_EVAL"
	phaseALFinalize       = "AL_FINALIZE"
	phaseSimTrain         = "SIM_TRAIN"
	phaseSimScore         = "SIM_SCORE"
	phaseSimSelect        = "SIM_SELECT"
	phaseSimActivate      = "SIM_ACTIVATE"
	phaseSimEval          = "SIM_EVAL"
	phaseSimFinalize      = "SIM_FINALIZE"
	phaseManualTrain      = "MANUAL_TRAIN"
	phaseManualEval       = "MANUAL_EVAL"
	phaseManualExport     = "MANUAL_EXPORT"
	phaseManualFinalize   = "MANUAL_FINALIZE"

	modeAL     = "ACTIVE_LEARNING"
	modeSIM    = "SIMULATION"
	modeManual = "MANUAL"

	roundPending   = "PENDING"
	roundRunning   = "RUNNING"
	roundWaitUser  = "WAIT_USER"
	roundCompleted = "COMPLETED"
	roundFailed    = "FAILED"
	roundCancelled = "CANCELLED"

	stepPending     = "PENDING"
	stepReady       = "READY"
	stepDispatching = "DISPATCHING"
	stepRunning     = "RUNNING"
	stepRetrying    = "RETRYING"
	stepSucceeded   = "SUCCEEDED"
	stepFailed      = "FAILED"
	stepCancelled   = "CANCELLED"
	stepSkipped     = "SKIPPED"

	terminalReasonSuccess     = "SUCCESS"
	terminalReasonSystemError = "SYSTEM_ERROR"
	terminalReasonUserStop    = "USER_STOP"
)

var terminalRoundStatuses = map[string]struct{}{
	roundCompleted: {},
	roundFailed:    {},
	roundCancelled: {},
}

type CommandResult struct {
	CommandID string
	Status    string
	Message   string
	RequestID string
}

type Service struct {
	repo                    *repo.RuntimeRepo
	dispatcher              *dispatch.Dispatcher
	domainClient            *runtime_domain_client.Client
	dispatchLockKey         int64
	simCooldown             time.Duration
	stopForceCancelAfter    time.Duration
	predictionTTLDays       int
	predictionTTLKeepRounds int
	lastTTLCleanupAt        time.Time
	ttlCleanupInterval      time.Duration
	logger                  zerolog.Logger
}

func NewService(
	repository *repo.RuntimeRepo,
	dispatcher *dispatch.Dispatcher,
	domainClient *runtime_domain_client.Client,
	dispatchLockKey int64,
	simulationCooldownSec int,
	stoppingForceCancelSec int,
	predictionTTLDays int,
	predictionTTLKeepRounds int,
	logger zerolog.Logger,
) *Service {
	if simulationCooldownSec < 0 {
		simulationCooldownSec = 0
	}
	if stoppingForceCancelSec < 0 {
		stoppingForceCancelSec = 0
	}
	if predictionTTLDays < 0 {
		predictionTTLDays = 0
	}
	if predictionTTLKeepRounds < 0 {
		predictionTTLKeepRounds = 0
	}
	return &Service{
		repo:                    repository,
		dispatcher:              dispatcher,
		domainClient:            domainClient,
		dispatchLockKey:         dispatchLockKey,
		simCooldown:             time.Duration(simulationCooldownSec) * time.Second,
		stopForceCancelAfter:    time.Duration(stoppingForceCancelSec) * time.Second,
		predictionTTLDays:       predictionTTLDays,
		predictionTTLKeepRounds: predictionTTLKeepRounds,
		ttlCleanupInterval:      time.Hour,
		logger:                  logger,
	}
}

func (s *Service) StartLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "start_loop", loopID, func(tx pgx.Tx, commandID string) (string, string, error) {
		loop, ok, err := s.lockLoop(ctx, tx, loopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}
		if loop.Status != statusDraft && loop.Status != statusStopped {
			return "rejected", fmt.Sprintf("loop in status %s cannot be started", loop.Status), nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasRound(ctx, tx, loop, commandID); err != nil {
			return "", "", err
		}
		return "applied", "start_loop applied", nil
	})
}

func (s *Service) PauseLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "pause_loop", loopID, func(tx pgx.Tx, _ string) (string, string, error) {
		loop, ok, err := s.lockLoop(ctx, tx, loopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}
		if loop.Status != statusRunning {
			return "rejected", fmt.Sprintf("loop in status %s cannot be paused", loop.Status), nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusPaused); err != nil {
			return "", "", err
		}
		return "applied", "pause_loop applied", nil
	})
}

func (s *Service) ResumeLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "resume_loop", loopID, func(tx pgx.Tx, commandID string) (string, string, error) {
		loop, ok, err := s.lockLoop(ctx, tx, loopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}
		if loop.Status != statusPaused {
			return "rejected", fmt.Sprintf("loop in status %s cannot be resumed", loop.Status), nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasRound(ctx, tx, loop, commandID); err != nil {
			return "", "", err
		}
		return "applied", "resume_loop applied", nil
	})
}

func (s *Service) StopLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "stop_loop", loopID, func(tx pgx.Tx, _ string) (string, string, error) {
		loop, ok, err := s.lockLoop(ctx, tx, loopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}
		if loop.Status != statusRunning && loop.Status != statusPaused {
			return "rejected", fmt.Sprintf("loop in status %s cannot be stopped", loop.Status), nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusStopping); err != nil {
			return "", "", err
		}
		return "applied", "stop_loop accepted (stopping)", nil
	})
}

func (s *Service) ConfirmLoop(
	ctx context.Context,
	commandID string,
	loopID string,
	force bool,
) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "confirm_loop", loopID, func(tx pgx.Tx, commandID string) (string, string, error) {
		loop, ok, err := s.lockLoop(ctx, tx, loopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}

		switch loop.Mode {
		case modeManual:
			return "rejected", "manual mode is single-run and does not require confirm", nil

		case modeAL:
			if loop.Phase != phaseALWaitAnnotation {
				return "rejected", "active-learning loop is not waiting for annotation", nil
			}
			nextRound, err := s.getNextRoundIndexTx(ctx, tx, loop.ID)
			if err != nil {
				return "", "", err
			}
			if nextRound > loop.MaxRounds {
				if err := s.updateLoopState(
					ctx,
					tx,
					loop.ID,
					statusCompleted,
					phaseALFinalize,
					terminalReasonSuccess,
					loop.LastConfirmedCommitID,
				); err != nil {
					return "", "", err
				}
				return "applied", "active-learning loop completed", nil
			}

			latestCommitID := loop.LastConfirmedCommitID
			if !force {
				newLabels, latestCommit, err := s.countNewLabels(ctx, loop.ProjectID, loop.BranchID, loop.LastConfirmedCommitID)
				if err != nil {
					return "", "", err
				}
				if newLabels <= 0 {
					return "rejected", "no new labels since last confirmation", nil
				}
				latestCommitID = latestCommit
			} else {
				headCommitID, _, err := s.resolveBranchHead(ctx, loop.BranchID)
				if err == nil {
					latestCommitID = headCommitID
				}
			}

			created, err := s.createNextRoundTx(ctx, tx, loop, commandID)
			if err != nil {
				return "", "", err
			}
			if !created {
				return "rejected", "cannot create next round for active-learning loop", nil
			}
			if latestCommitID != "" {
				if _, err := tx.Exec(
					ctx,
					`UPDATE loop SET last_confirmed_commit_id=$2::uuid,updated_at=now() WHERE id=$1::uuid`,
					loop.ID,
					latestCommitID,
				); err != nil {
					return "", "", err
				}
			}
			return "applied", "active-learning confirm accepted", nil

		case modeSIM:
			return "rejected", "simulation loop does not require manual confirm", nil
		default:
			return "rejected", "unsupported loop mode", nil
		}
	})
}

func (s *Service) StopRound(ctx context.Context, commandID string, roundID string, reason string) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}
	return s.withCommand(ctx, commandID, "stop_round", roundID, func(tx pgx.Tx, _ string) (string, string, error) {
		var currentStatus string
		if err := tx.QueryRow(
			ctx,
			`SELECT COALESCE(state::text,'') FROM round WHERE id=$1::uuid`,
			roundID,
		).Scan(&currentStatus); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return "rejected", "round not found", nil
			}
			return "", "", err
		}
		if _, ok := terminalRoundStatuses[currentStatus]; ok {
			return "applied", "round already in terminal state", nil
		}

		if _, err := tx.Exec(
			ctx,
			`UPDATE round SET state=$2::roundstatus,terminal_reason=$3,updated_at=now() WHERE id=$1::uuid`,
			roundID,
			roundCancelled,
			reason,
		); err != nil {
			return "", "", err
		}
		rows, err := tx.Query(
			ctx,
			`SELECT id::text FROM step
				 WHERE round_id=$1::uuid
				   AND state IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
			roundID,
		)
		if err != nil {
			return "", "", err
		}
		stepIDs := make([]string, 0, 16)
		for rows.Next() {
			var stepID string
			if scanErr := rows.Scan(&stepID); scanErr != nil {
				rows.Close()
				return "", "", scanErr
			}
			stepIDs = append(stepIDs, stepID)
		}
		rows.Close()
		if _, err := tx.Exec(
			ctx,
			`UPDATE step
				 SET state='CANCELLED',last_error=$2,ended_at=COALESCE(ended_at,now()),updated_at=now()
				 WHERE round_id=$1::uuid
				   AND state IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
			roundID,
			reason,
		); err != nil {
			return "", "", err
		}
		for _, stepID := range stepIDs {
			s.dispatcher.StopStep(stepID, reason)
		}
		return "applied", "stop_round applied", nil
	})
}

func (s *Service) StopStep(ctx context.Context, commandID string, stepID string, reason string) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}
	return s.withCommand(ctx, commandID, "stop_step", stepID, func(tx pgx.Tx, _ string) (string, string, error) {
		var currentStatus string
		if err := tx.QueryRow(
			ctx,
			`SELECT COALESCE(state::text,'') FROM step WHERE id=$1::uuid`,
			stepID,
		).Scan(&currentStatus); err != nil {
			if err == pgx.ErrNoRows {
				return "rejected", "step not found", nil
			}
			return "", "", err
		}
		if currentStatus == stepSucceeded || currentStatus == stepFailed || currentStatus == stepCancelled || currentStatus == stepSkipped {
			return "applied", "step already in terminal state", nil
		}

		if _, err := tx.Exec(
			ctx,
			`UPDATE step
			 SET state='CANCELLED',last_error=$2,ended_at=COALESCE(ended_at,now()),updated_at=now()
			 WHERE id=$1::uuid`,
			stepID,
			reason,
		); err != nil {
			return "", "", err
		}
		s.dispatcher.StopStep(stepID, reason)
		return "applied", "stop_step applied", nil
	})
}

func (s *Service) TriggerDispatch(ctx context.Context, commandID string, stepID string) (CommandResult, error) {
	stepID = strings.TrimSpace(stepID)
	return s.withCommand(ctx, commandID, "trigger_dispatch", stepID, func(tx pgx.Tx, _ string) (string, string, error) {
		if stepID != "" {
			dispatched, err := s.dispatchStepByID(ctx, stepID)
			if err != nil {
				return "", "", err
			}
			if !dispatched {
				return "applied", "step not dispatched", nil
			}
			return "applied", "step dispatched", nil
		}
		count, err := s.dispatchPending(ctx, 128)
		if err != nil {
			return "", "", err
		}
		return "applied", fmt.Sprintf("dispatch scan completed, dispatched=%d", count), nil
	})
}

func (s *Service) Tick(ctx context.Context) error {
	if !s.repo.Enabled() {
		return nil
	}
	s.maybeCleanupPredictionRows(ctx)
	loopIDs, err := s.listTickLoopIDs(ctx, 512)
	if err != nil {
		return err
	}
	for _, loopID := range loopIDs {
		if err := s.processLoop(ctx, loopID); err != nil {
			s.logger.Warn().Str("loop_id", loopID).Err(err).Msg("process loop failed")
		}
	}
	_, err = s.dispatchPending(ctx, 256)
	return err
}

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
	tx, err := s.repo.Begin(ctx)
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
	result, err := tx.Exec(
		ctx,
		`WITH ranked_rounds AS (
		    SELECT r.id AS round_id,
		           ROW_NUMBER() OVER (PARTITION BY r.loop_id ORDER BY r.round_index DESC) AS round_rank
		      FROM round r
		  ),
		  eligible_steps AS (
		    SELECT s.id AS step_id
		      FROM step s
		      JOIN round r ON r.id = s.round_id
		      JOIN ranked_rounds rr ON rr.round_id = r.id
		     WHERE s.step_type = 'SCORE'
		       AND COALESCE(s.ended_at, s.updated_at, s.created_at) < $1
		       AND rr.round_rank > $2
		  )
		  DELETE FROM step_candidate_item c
		   WHERE c.step_id IN (SELECT step_id FROM eligible_steps)`,
		cutoff,
		keepRounds,
	)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected(), nil
}

func (s *Service) deletePredictionEventsTx(ctx context.Context, tx pgx.Tx, cutoff time.Time, keepRounds int) (int64, error) {
	result, err := tx.Exec(
		ctx,
		`WITH ranked_rounds AS (
		    SELECT r.id AS round_id,
		           ROW_NUMBER() OVER (PARTITION BY r.loop_id ORDER BY r.round_index DESC) AS round_rank
		      FROM round r
		  ),
		  eligible_steps AS (
		    SELECT s.id AS step_id
		      FROM step s
		      JOIN round r ON r.id = s.round_id
		      JOIN ranked_rounds rr ON rr.round_id = r.id
		     WHERE s.step_type = 'SCORE'
		       AND COALESCE(s.ended_at, s.updated_at, s.created_at) < $1
		       AND rr.round_rank > $2
		  )
		  DELETE FROM step_event e
		   WHERE e.step_id IN (SELECT step_id FROM eligible_steps)
		     AND e.event_type = ANY($3::text[])`,
		cutoff,
		keepRounds,
		[]string{"metric", "progress", "log"},
	)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected(), nil
}

func (s *Service) deletePredictionMetricsTx(ctx context.Context, tx pgx.Tx, cutoff time.Time, keepRounds int) (int64, error) {
	result, err := tx.Exec(
		ctx,
		`WITH ranked_rounds AS (
		    SELECT r.id AS round_id,
		           ROW_NUMBER() OVER (PARTITION BY r.loop_id ORDER BY r.round_index DESC) AS round_rank
		      FROM round r
		  ),
		  eligible_steps AS (
		    SELECT s.id AS step_id
		      FROM step s
		      JOIN round r ON r.id = s.round_id
		      JOIN ranked_rounds rr ON rr.round_id = r.id
		     WHERE s.step_type = 'SCORE'
		       AND COALESCE(s.ended_at, s.updated_at, s.created_at) < $1
		       AND rr.round_rank > $2
		  )
		  DELETE FROM step_metric_point m
		   WHERE m.step_id IN (SELECT step_id FROM eligible_steps)`,
		cutoff,
		keepRounds,
	)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected(), nil
}

func (s *Service) OnExecutorRegister(ctx context.Context, register *runtimecontrolv1.Register) error {
	if !s.repo.Enabled() || register == nil {
		return nil
	}
	executorID := strings.TrimSpace(register.GetExecutorId())
	if executorID == "" {
		return nil
	}
	version := strings.TrimSpace(register.GetVersion())

	pluginPayloadJSON, err := marshalJSON(map[string]any{
		"plugins": pluginCapabilitiesToMaps(register.GetPlugins()),
	})
	if err != nil {
		return err
	}
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(register.GetResources()))
	if err != nil {
		return err
	}

	_, err = s.repo.Pool().Exec(
		ctx,
		`INSERT INTO runtime_executor(
		     id,executor_id,version,status,is_online,current_step_id,plugin_ids,resources,last_seen_at,last_error,created_at,updated_at
		   ) VALUES(
		     $1::uuid,$2,$3,'idle',TRUE,NULL,$4::jsonb,$5::jsonb,now(),NULL,now(),now()
		   )
		   ON CONFLICT (executor_id) DO UPDATE SET
		     version=EXCLUDED.version,
		     status='idle',
		     is_online=TRUE,
		     current_step_id=NULL,
		     plugin_ids=EXCLUDED.plugin_ids,
		     resources=EXCLUDED.resources,
		     last_seen_at=EXCLUDED.last_seen_at,
		     last_error=NULL,
		     updated_at=now()`,
		uuid.NewString(),
		executorID,
		version,
		pluginPayloadJSON,
		resourcesJSON,
	)
	return err
}

func (s *Service) OnExecutorHeartbeat(ctx context.Context, heartbeat *runtimecontrolv1.Heartbeat) error {
	if !s.repo.Enabled() || heartbeat == nil {
		return nil
	}
	executorID := strings.TrimSpace(heartbeat.GetExecutorId())
	if executorID == "" {
		return nil
	}

	status := "idle"
	if heartbeat.GetBusy() {
		status = "busy"
	}
	currentStepID := strings.TrimSpace(heartbeat.GetCurrentStepId())
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(heartbeat.GetResources()))
	if err != nil {
		return err
	}

	_, err = s.repo.Pool().Exec(
		ctx,
		`INSERT INTO runtime_executor(
		     id,executor_id,version,status,is_online,current_step_id,plugin_ids,resources,last_seen_at,last_error,created_at,updated_at
		   ) VALUES(
		     $1::uuid,$2,'',$3,TRUE,NULLIF($4,''),'{}'::jsonb,$5::jsonb,now(),NULL,now(),now()
		   )
		   ON CONFLICT (executor_id) DO UPDATE SET
		     status=EXCLUDED.status,
		     is_online=TRUE,
		     current_step_id=EXCLUDED.current_step_id,
		     resources=EXCLUDED.resources,
		     last_seen_at=EXCLUDED.last_seen_at,
		     last_error=NULL,
		     updated_at=now()`,
		uuid.NewString(),
		executorID,
		status,
		currentStepID,
		resourcesJSON,
	)
	return err
}

func (s *Service) OnExecutorDisconnected(ctx context.Context, executorID string, reason string) error {
	if !s.repo.Enabled() {
		return nil
	}
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return nil
	}

	_, err := s.repo.Pool().Exec(
		ctx,
		`UPDATE runtime_executor
		 SET status='offline',
		     is_online=FALSE,
		     current_step_id=NULL,
		     last_error=NULLIF($2,''),
		     last_seen_at=now(),
		     updated_at=now()
		 WHERE executor_id=$1`,
		executorID,
		strings.TrimSpace(reason),
	)
	return err
}

func (s *Service) OnStepEvent(ctx context.Context, event *runtimecontrolv1.StepEvent) error {
	if !s.repo.Enabled() || event == nil {
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

	tx, err := s.repo.Begin(ctx)
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
		tag, err := tx.Exec(
			ctx,
			`UPDATE step
			 SET state=$2::stepstatus,
			     started_at=CASE WHEN $2::stepstatus='RUNNING'::stepstatus THEN COALESCE(started_at,now()) ELSE started_at END,
			     ended_at=CASE WHEN $2::stepstatus IN ('SUCCEEDED'::stepstatus,'FAILED'::stepstatus,'CANCELLED'::stepstatus,'SKIPPED'::stepstatus) THEN COALESCE(ended_at,now()) ELSE ended_at END,
			     last_error=CASE WHEN $2::stepstatus IN ('SUCCEEDED'::stepstatus,'FAILED'::stepstatus,'CANCELLED'::stepstatus,'SKIPPED'::stepstatus) THEN NULLIF($3,'') ELSE last_error END,
			     updated_at=now()
			 WHERE id=$1::uuid`,
			stepID,
			statusDB,
			strings.TrimSpace(event.GetStatusEvent().GetReason()),
		)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
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
	if !s.repo.Enabled() || result == nil {
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

	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	tag, err := tx.Exec(
		ctx,
		`UPDATE step
		 SET state=$2::stepstatus,
		     metrics=$3::jsonb,
		     artifacts=$4::jsonb,
		     last_error=NULLIF($5,''),
		     started_at=COALESCE(started_at,now()),
		     ended_at=CASE WHEN $2::stepstatus IN ('SUCCEEDED'::stepstatus,'FAILED'::stepstatus,'CANCELLED'::stepstatus,'SKIPPED'::stepstatus) THEN COALESCE(ended_at,now()) ELSE ended_at END,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		stepID,
		statusDB,
		metricsJSON,
		artifactsJSON,
		strings.TrimSpace(result.GetErrorMessage()),
	)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
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

func (s *Service) withCommand(
	ctx context.Context,
	commandID string,
	commandType string,
	resourceID string,
	action func(tx pgx.Tx, normalizedCommandID string) (status string, detail string, err error),
) (CommandResult, error) {
	commandID = strings.TrimSpace(commandID)
	if commandID == "" {
		commandID = uuid.NewString()
	}
	resourceID = strings.TrimSpace(resourceID)
	if !s.repo.Enabled() {
		return CommandResult{
			CommandID: commandID,
			Status:    "failed",
			Message:   "database is not configured",
			RequestID: uuid.NewString(),
		}, nil
	}

	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return CommandResult{}, err
	}
	defer tx.Rollback(ctx)

	entry, found, err := s.getCommandLogTx(ctx, tx, commandID)
	if err != nil {
		return CommandResult{}, err
	}
	if found {
		return CommandResult{
			CommandID: commandID,
			Status:    entry.Status,
			Message:   entry.Detail,
			RequestID: entry.ID,
		}, nil
	}

	requestID := uuid.NewString()
	inserted, err := s.insertCommandLogTx(ctx, tx, requestID, commandID, commandType, resourceID)
	if err != nil {
		return CommandResult{}, err
	}
	if !inserted {
		entry, found, err := s.getCommandLogTx(ctx, tx, commandID)
		if err != nil {
			return CommandResult{}, err
		}
		if found {
			return CommandResult{
				CommandID: commandID,
				Status:    entry.Status,
				Message:   entry.Detail,
				RequestID: entry.ID,
			}, nil
		}
	}

	status, detail, err := action(tx, commandID)
	if err != nil {
		return CommandResult{}, err
	}
	if status == "" {
		status = "applied"
	}
	if detail == "" {
		detail = status
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE runtime_command_log SET status=$2,detail=$3,updated_at=now() WHERE command_id=$1`,
		commandID,
		status,
		detail,
	); err != nil {
		return CommandResult{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return CommandResult{}, err
	}
	return CommandResult{
		CommandID: commandID,
		Status:    status,
		Message:   detail,
		RequestID: requestID,
	}, nil
}

func (s *Service) listTickLoopIDs(ctx context.Context, limit int) ([]string, error) {
	rows, err := s.repo.Pool().Query(
		ctx,
		`SELECT id::text FROM loop
		  WHERE status IN ('RUNNING','STOPPING')
		  ORDER BY updated_at ASC
		  LIMIT $1`,
		max(1, limit),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	loopIDs := make([]string, 0, limit)
	for rows.Next() {
		var loopID string
		if err := rows.Scan(&loopID); err != nil {
			return nil, err
		}
		loopIDs = append(loopIDs, loopID)
	}
	return loopIDs, rows.Err()
}

func (s *Service) processLoop(ctx context.Context, loopID string) error {
	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	loop, ok, err := s.lockLoop(ctx, tx, loopID)
	if err != nil {
		return err
	}
	if !ok {
		return tx.Commit(ctx)
	}

	switch loop.Status {
	case statusStopping:
		return s.processStoppingLoopTx(ctx, tx, loop)
	case statusRunning:
		if err := s.processRunningLoopTx(ctx, tx, loop); err != nil {
			return err
		}
		return tx.Commit(ctx)
	default:
		return tx.Commit(ctx)
	}
}

func (s *Service) processRunningLoopTx(ctx context.Context, tx pgx.Tx, loop loopRow) error {
	latestRound, hasRound, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return err
	}
	if !hasRound {
		_, err := s.createNextRoundTx(ctx, tx, loop, uuid.NewString())
		return err
	}

	roundStatus, err := s.refreshRoundAggregateTx(ctx, tx, latestRound.ID)
	if err != nil {
		return err
	}
	if loop.Mode == modeAL && roundStatus == roundCompleted {
		if _, err := tx.Exec(
			ctx,
			`UPDATE round
			 SET state='WAIT_USER'::roundstatus,
			     ended_at=COALESCE(ended_at,now()),
			     updated_at=now()
			 WHERE id=$1::uuid`,
			latestRound.ID,
		); err != nil {
			return err
		}
		roundStatus = roundWaitUser
	}
	if _, ok := terminalRoundStatuses[roundStatus]; !ok {
		if loop.Mode == modeAL && roundStatus == roundWaitUser {
			return s.updateLoopState(ctx, tx, loop.ID, statusRunning, phaseALWaitAnnotation, "", loop.LastConfirmedCommitID)
		}
		return nil
	}

	if roundStatus == roundFailed || roundStatus == roundCancelled {
		if err := s.updateLoopState(
			ctx,
			tx,
			loop.ID,
			statusFailed,
			loop.Phase,
			terminalReasonSystemError,
			loop.LastConfirmedCommitID,
		); err != nil {
			return err
		}
		return nil
	}

	switch loop.Mode {
	case modeSIM:
		if latestRound.RoundIndex >= loop.MaxRounds {
			if err := s.updateLoopState(
				ctx,
				tx,
				loop.ID,
				statusCompleted,
				phaseSimFinalize,
				terminalReasonSuccess,
				loop.LastConfirmedCommitID,
			); err != nil {
				return err
			}
		} else {
			if s.shouldDelaySimulationRound(latestRound.EndedAt) {
				return nil
			}
			if _, err := s.createNextRoundTx(ctx, tx, loop, uuid.NewString()); err != nil {
				return err
			}
		}
	case modeManual:
		if err := s.updateLoopState(
			ctx,
			tx,
			loop.ID,
			statusCompleted,
			phaseManualFinalize,
			terminalReasonSuccess,
			loop.LastConfirmedCommitID,
		); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) processStoppingLoopTx(ctx context.Context, tx pgx.Tx, loop loopRow) error {
	rows, err := tx.Query(
		ctx,
		`SELECT t.id::text,
		        COALESCE(t.state::text,''),
		        t.attempt,
		        t.updated_at
		   FROM step t
		   JOIN round j ON j.id=t.round_id
		  WHERE j.loop_id=$1::uuid
		    AND t.state IN ('PENDING','DISPATCHING','RUNNING','RETRYING')
		  ORDER BY t.created_at ASC`,
		loop.ID,
	)
	if err != nil {
		return err
	}
	type stoppingStep struct {
		ID        string
		State     string
		Attempt   int
		UpdatedAt time.Time
	}
	tasks := make([]stoppingStep, 0)
	for rows.Next() {
		var item stoppingStep
		if err := rows.Scan(&item.ID, &item.State, &item.Attempt, &item.UpdatedAt); err != nil {
			rows.Close()
			return err
		}
		tasks = append(tasks, item)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	if len(tasks) > 0 {
		reason := "loop stopping requested"
		immediateCancelStepIDs := make([]string, 0, len(tasks))
		forceCancelStepIDs := make([]string, 0, len(tasks))
		hasInflightRunning := false
		now := time.Now().UTC()

		for _, item := range tasks {
			normalizedState := strings.ToUpper(strings.TrimSpace(item.State))
			switch normalizedState {
			case stepPending:
				immediateCancelStepIDs = append(immediateCancelStepIDs, item.ID)
			case stepDispatching:
				if _, err := s.issueCancelAttemptTx(ctx, tx, item.ID, item.Attempt, reason); err != nil {
					return err
				}
				immediateCancelStepIDs = append(immediateCancelStepIDs, item.ID)
			case stepRunning, stepRetrying:
				if _, err := s.issueCancelAttemptTx(ctx, tx, item.ID, item.Attempt, reason); err != nil {
					return err
				}
				if s.stopForceCancelAfter > 0 && now.Sub(item.UpdatedAt.UTC()) >= s.stopForceCancelAfter {
					forceCancelStepIDs = append(forceCancelStepIDs, item.ID)
					continue
				}
				hasInflightRunning = true
			}
		}
		if err := s.cancelStepIDsTx(ctx, tx, immediateCancelStepIDs, reason); err != nil {
			return err
		}
		if len(forceCancelStepIDs) > 0 {
			forceReason := fmt.Sprintf("%s (force-timeout)", reason)
			if err := s.cancelStepIDsTx(ctx, tx, forceCancelStepIDs, forceReason); err != nil {
				return err
			}
			for _, stepID := range forceCancelStepIDs {
				s.logger.Warn().
					Str("loop_id", loop.ID).
					Str("step_id", stepID).
					Dur("force_after", s.stopForceCancelAfter).
					Msg("force cancel step in stopping loop after timeout")
			}
		}
		if hasInflightRunning {
			return tx.Commit(ctx)
		}

		active, err := s.loopHasActiveStepsTx(ctx, tx, loop.ID)
		if err != nil {
			return err
		}
		if active {
			return tx.Commit(ctx)
		}
	}

	if err := s.updateLoopState(
		ctx,
		tx,
		loop.ID,
		statusStopped,
		loop.Phase,
		terminalReasonUserStop,
		loop.LastConfirmedCommitID,
	); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Service) shouldDelaySimulationRound(lastEndedAt *time.Time) bool {
	if s.simCooldown <= 0 || lastEndedAt == nil || lastEndedAt.IsZero() {
		return false
	}
	return time.Since(lastEndedAt.UTC()) < s.simCooldown
}

func (s *Service) dispatchPending(ctx context.Context, limit int) (int, error) {
	if !s.repo.Enabled() {
		return 0, nil
	}
	if s.dispatchLockKey != 0 {
		conn, err := s.repo.Pool().Acquire(ctx)
		if err != nil {
			return 0, err
		}
		defer conn.Release()

		var locked bool
		if err := conn.QueryRow(ctx, `SELECT pg_try_advisory_lock($1)`, s.dispatchLockKey).Scan(&locked); err != nil {
			return 0, err
		}
		if !locked {
			return 0, nil
		}
		defer func() {
			var unlocked bool
			if err := conn.QueryRow(context.Background(), `SELECT pg_advisory_unlock($1)`, s.dispatchLockKey).Scan(&unlocked); err != nil {
				s.logger.Warn().Err(err).Msg("release dispatch advisory lock failed")
			}
		}()
	}

	count := 0
	for _, queuedStepID := range s.dispatcher.DrainQueuedStepIDs() {
		dispatched, err := s.dispatchStepByID(ctx, queuedStepID)
		if err != nil {
			return count, err
		}
		if dispatched {
			count++
		}
	}

	stepIDs, err := s.listPendingStepIDs(ctx, limit)
	if err != nil {
		return count, err
	}
	for _, stepID := range stepIDs {
		dispatched, err := s.dispatchStepByID(ctx, stepID)
		if err != nil {
			return count, err
		}
		if dispatched {
			count++
		}
	}
	return count, nil
}

func (s *Service) dispatchStepByID(ctx context.Context, stepID string) (bool, error) {
	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	stepPayload, ok, err := s.getStepPayloadByIDTx(ctx, tx, stepID)
	if err != nil {
		return false, err
	}
	if !ok || stepPayload.Status != stepPending {
		return false, tx.Commit(ctx)
	}

	depsOK, err := s.dependenciesSatisfiedTx(ctx, tx, stepPayload.DependsOnStepIDs)
	if err != nil {
		return false, err
	}
	if !depsOK {
		return false, tx.Commit(ctx)
	}
	var loopStatus string
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(status::text,'') FROM loop WHERE id=$1::uuid`,
		stepPayload.LoopID,
	).Scan(&loopStatus); err != nil {
		if err == pgx.ErrNoRows {
			return false, tx.Commit(ctx)
		}
		return false, err
	}
	if strings.TrimSpace(loopStatus) != statusRunning {
		return false, tx.Commit(ctx)
	}
	if isOrchestratorDispatchKind(stepPayload.DispatchKind) {
		executed, err := s.executeOrchestratorStepTx(ctx, tx, stepPayload)
		if err != nil {
			return false, err
		}
		return executed, tx.Commit(ctx)
	}

	executorID, found := s.dispatcher.PickExecutor(stepPayload.PluginID)
	if !found {
		return false, tx.Commit(ctx)
	}
	requestID := uuid.NewString()
	updated, err := s.markStepDispatchingTx(ctx, tx, stepPayload.StepID, executorID, requestID)
	if err != nil {
		return false, err
	}
	if !updated {
		return false, tx.Commit(ctx)
	}

	message := &runtimecontrolv1.StepPayload{
		StepId:           stepPayload.StepID,
		RoundId:          stepPayload.RoundID,
		LoopId:           stepPayload.LoopID,
		ProjectId:        stepPayload.ProjectID,
		InputCommitId:    stepPayload.InputCommitID,
		StepType:         toRuntimeStepType(stepPayload.StepType),
		DispatchKind:     toRuntimeStepDispatchKind(stepPayload.DispatchKind),
		PluginId:         stepPayload.PluginID,
		Mode:             toRuntimeLoopMode(stepPayload.Mode),
		QueryStrategy:    stepPayload.QueryStrategy,
		ResolvedParams:   stepPayload.Params,
		Resources:        stepPayload.Resources,
		RoundIndex:       int32(stepPayload.RoundIndex),
		Attempt:          int32(stepPayload.Attempt),
		DependsOnStepIds: stepPayload.DependsOnStepIDs,
	}
	if !s.dispatcher.DispatchStep(executorID, requestID, message) {
		if _, err := tx.Exec(
			ctx,
			`UPDATE step SET state='PENDING',assigned_executor_id=NULL,last_error='dispatcher queue full',updated_at=now() WHERE id=$1::uuid`,
			stepPayload.StepID,
		); err != nil {
			return false, err
		}
		return false, tx.Commit(ctx)
	}
	return true, tx.Commit(ctx)
}

func isOrchestratorStepType(stepType string) bool {
	switch strings.ToUpper(strings.TrimSpace(stepType)) {
	case "SELECT":
		return true
	case "ACTIVATE_SAMPLES":
		return true
	case "ADVANCE_BRANCH":
		return true
	default:
		return false
	}
}

func isOrchestratorDispatchKind(dispatchKind string) bool {
	return strings.EqualFold(strings.TrimSpace(dispatchKind), "ORCHESTRATOR")
}

func (s *Service) executeOrchestratorStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
) (bool, error) {
	started, err := tx.Exec(
		ctx,
		`UPDATE step
		    SET state='RUNNING',
		        started_at=COALESCE(started_at,now()),
		        updated_at=now()
		  WHERE id=$1::uuid
		    AND state='PENDING'`,
		stepPayload.StepID,
	)
	if err != nil {
		return false, err
	}
	if started.RowsAffected() == 0 {
		return false, nil
	}

	resultStatus := stepSucceeded
	lastError := ""
	resultCommitID := ""
	if err := s.runOrchestratorStepTx(ctx, tx, stepPayload, &resultCommitID); err != nil {
		resultStatus = stepFailed
		lastError = err.Error()
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE step
		    SET state=$2::stepstatus,
		        last_error=NULLIF($3,''),
		        output_commit_id=NULLIF($4,'')::uuid,
		        ended_at=COALESCE(ended_at,now()),
		        updated_at=now()
		  WHERE id=$1::uuid`,
		stepPayload.StepID,
		resultStatus,
		lastError,
		resultCommitID,
	); err != nil {
		return false, err
	}

	if strings.TrimSpace(resultCommitID) != "" {
		if _, err := tx.Exec(
			ctx,
			`UPDATE round
			    SET output_commit_id=NULLIF($2,'')::uuid,
			        updated_at=now()
			  WHERE id=$1::uuid`,
			stepPayload.RoundID,
			resultCommitID,
		); err != nil {
			return false, err
		}
	}

	if _, err := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) runOrchestratorStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
	resultCommitID *string,
) error {
	switch strings.ToUpper(strings.TrimSpace(stepPayload.StepType)) {
	case "SELECT":
		return s.runSelectTopKTx(ctx, tx, stepPayload)
	case "ACTIVATE_SAMPLES":
		return s.runActivateSamplesTx(ctx, tx, stepPayload, resultCommitID)
	case "ADVANCE_BRANCH":
		return s.runAdvanceBranchTx(ctx, tx, stepPayload, resultCommitID)
	default:
		return nil
	}
}

func (s *Service) runSelectTopKTx(ctx context.Context, tx pgx.Tx, stepPayload stepDispatchPayload) error {
	var queryBatch int
	if err := tx.QueryRow(
		ctx,
		`SELECT query_batch_size FROM loop WHERE id=$1::uuid`,
		stepPayload.LoopID,
	).Scan(&queryBatch); err != nil {
		return err
	}
	if queryBatch <= 0 {
		queryBatch = 1
	}

	var scoreStepID string
	if err := tx.QueryRow(
		ctx,
		`SELECT id::text
		   FROM step
		  WHERE round_id=$1::uuid
		    AND step_type='SCORE'
		    AND state='SUCCEEDED'
		  ORDER BY step_index DESC
		  LIMIT 1`,
		stepPayload.RoundID,
	).Scan(&scoreStepID); err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("score step not ready for select step %s", stepPayload.StepID)
		}
		return err
	}

	rows, err := tx.Query(
		ctx,
		`SELECT sample_id::text,
		        rank,
		        score,
		        COALESCE(reason::text,'{}'),
		        COALESCE(prediction_snapshot::text,'{}')
		   FROM step_candidate_item
		  WHERE step_id=$1::uuid
		  ORDER BY rank ASC, score DESC
		  LIMIT $2`,
		scoreStepID,
		queryBatch,
	)
	if err != nil {
		return err
	}
	defer rows.Close()

	type candidateRow struct {
		sampleID       string
		score          float64
		reasonJSON     string
		predictionJSON string
	}
	candidates := make([]candidateRow, 0, queryBatch)
	for rows.Next() {
		var (
			row  candidateRow
			rank int
		)
		if err := rows.Scan(&row.sampleID, &rank, &row.score, &row.reasonJSON, &row.predictionJSON); err != nil {
			return err
		}
		_ = rank
		candidates = append(candidates, row)
	}
	if err := rows.Err(); err != nil {
		return err
	}

	if _, err := tx.Exec(ctx, `DELETE FROM step_candidate_item WHERE step_id=$1::uuid`, stepPayload.StepID); err != nil {
		return err
	}

	for idx, item := range candidates {
		parsedSampleID, err := uuid.Parse(strings.TrimSpace(item.sampleID))
		if err != nil {
			continue
		}
		if _, err := tx.Exec(
			ctx,
			`INSERT INTO step_candidate_item(
			     id,step_id,sample_id,rank,score,reason,prediction_snapshot,created_at,updated_at
			   ) VALUES(
			     $1::uuid,$2::uuid,$3::uuid,$4,$5,$6::jsonb,$7::jsonb,now(),now()
			   )`,
			uuid.NewString(),
			stepPayload.StepID,
			parsedSampleID.String(),
			idx+1,
			item.score,
			item.reasonJSON,
			item.predictionJSON,
		); err != nil {
			return err
		}
	}

	return nil
}

func (s *Service) runActivateSamplesTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
	resultCommitID *string,
) error {
	if s.domainClient == nil || !s.domainClient.Enabled() {
		return nil
	}

	var (
		projectID     string
		branchID      string
		queryStrategy string
		globalConfig  string
		queryBatch    int
	)
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(project_id::text,''),
		        COALESCE(branch_id::text,''),
		        COALESCE(query_strategy,''),
		        COALESCE(global_config::text,'{}'),
		        query_batch_size
		   FROM loop
		  WHERE id=$1::uuid`,
		stepPayload.LoopID,
	).Scan(&projectID, &branchID, &queryStrategy, &globalConfig, &queryBatch); err != nil {
		return err
	}

	oracleCommitID := extractOracleCommitID(globalConfig)
	if oracleCommitID == "" {
		return nil
	}

	sourceCommitID := strings.TrimSpace(stepPayload.InputCommitID)
	if sourceCommitID == "" {
		headCommitID, branchProjectID, err := s.resolveBranchHead(ctx, branchID)
		if err != nil {
			return err
		}
		sourceCommitID = strings.TrimSpace(headCommitID)
		if strings.TrimSpace(branchProjectID) != "" {
			projectID = branchProjectID
		}
	}

	commandID := activationCommandID(stepPayload)
	response, err := s.domainClient.ActivateSamples(ctx, &runtimedomainv1.ActivateSamplesRequest{
		CommandId:      commandID,
		ProjectId:      projectID,
		BranchId:       branchID,
		OracleCommitId: oracleCommitID,
		SourceCommitId: sourceCommitID,
		LoopId:         stepPayload.LoopID,
		RoundIndex:     int32(stepPayload.RoundIndex),
		QueryStrategy:  queryStrategy,
		Topk:           int32(queryBatch),
	})
	if err != nil {
		return err
	}
	commitID := strings.TrimSpace(response.GetCommitId())
	if commitID != "" {
		if resultCommitID != nil {
			*resultCommitID = commitID
		}
	}
	return nil
}

func (s *Service) runAdvanceBranchTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
	resultCommitID *string,
) error {
	if s.domainClient == nil || !s.domainClient.Enabled() {
		return nil
	}

	var branchID string
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(branch_id::text,'')
		   FROM loop
		  WHERE id=$1::uuid`,
		stepPayload.LoopID,
	).Scan(&branchID); err != nil {
		return err
	}
	branchID = strings.TrimSpace(branchID)
	if branchID == "" {
		return fmt.Errorf("loop %s branch_id is empty", stepPayload.LoopID)
	}

	var activateCommitID string
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(output_commit_id::text,'')
		   FROM step
		  WHERE round_id=$1::uuid
		    AND step_type='ACTIVATE_SAMPLES'
		    AND state='SUCCEEDED'
		  ORDER BY step_index DESC
		  LIMIT 1`,
		stepPayload.RoundID,
	).Scan(&activateCommitID); err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("activate_samples output commit not found for round %s", stepPayload.RoundID)
		}
		return err
	}
	activateCommitID = strings.TrimSpace(activateCommitID)
	if activateCommitID == "" {
		return fmt.Errorf("activate_samples output commit is empty for round %s", stepPayload.RoundID)
	}

	commandID := advanceBranchCommandID(stepPayload, activateCommitID)
	response, err := s.domainClient.AdvanceBranchHead(
		ctx,
		commandID,
		branchID,
		activateCommitID,
		fmt.Sprintf("loop=%s round=%d advance_branch_step=%s", stepPayload.LoopID, stepPayload.RoundIndex, stepPayload.StepID),
	)
	if err != nil {
		return err
	}
	if !response.GetAdvanced() {
		return fmt.Errorf("advance branch head rejected branch=%s commit=%s", branchID, activateCommitID)
	}
	if resultCommitID != nil {
		*resultCommitID = activateCommitID
	}
	return nil
}

func (s *Service) ensureLoopHasRound(ctx context.Context, tx pgx.Tx, loop loopRow, commandID string) (bool, error) {
	latestRound, hasRound, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return false, err
	}
	if !hasRound {
		return s.createNextRoundTx(ctx, tx, loop, commandID)
	}
	if _, ok := terminalRoundStatuses[latestRound.SummaryStatus]; ok && loop.Mode == modeSIM {
		return s.createNextRoundTx(ctx, tx, loop, commandID)
	}
	return false, nil
}

func (s *Service) getNextRoundIndexTx(ctx context.Context, tx pgx.Tx, loopID string) (int, error) {
	var currentMax int
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(MAX(round_index),0) FROM round WHERE loop_id=$1::uuid`,
		loopID,
	).Scan(&currentMax); err != nil {
		return 0, err
	}
	return currentMax + 1, nil
}

func (s *Service) createNextRoundTx(ctx context.Context, tx pgx.Tx, loop loopRow, commandID string) (bool, error) {
	nextRound, err := s.getNextRoundIndexTx(ctx, tx, loop.ID)
	if err != nil {
		return false, err
	}
	if nextRound > loop.MaxRounds {
		return false, nil
	}
	sourceCommitID, projectIDFromBranch, err := s.resolveBranchHead(ctx, loop.BranchID)
	if err != nil {
		s.logger.Warn().Err(err).Str("loop_id", loop.ID).Msg("resolve branch head failed, continue with empty source commit")
	}
	projectID := loop.ProjectID
	if projectIDFromBranch != "" {
		projectID = projectIDFromBranch
	}

	roundID := uuid.NewString()
	paramsJSON, err := marshalJSON(map[string]any{
		"round_index":    nextRound,
		"loop_mode":      loop.Mode,
		"query_strategy": loop.QueryStrategy,
	})
	if err != nil {
		return false, err
	}
	resourcesJSON := "{}"
	if resourcePayload := extractRoundResources(loop.GlobalConfig); resourcePayload != nil {
		if resourcesJSON, err = marshalJSON(resourcePayload); err != nil {
			return false, err
		}
	}

	if _, err := tx.Exec(
		ctx,
		`INSERT INTO round(
		     id,project_id,loop_id,round_index,mode,state,step_counts,round_type,plugin_id,query_strategy,
		     resolved_params,resources,input_commit_id,retry_count,terminal_reason,final_metrics,final_artifacts,strategy_params,
		     created_at,updated_at
		   ) VALUES (
		     $1::uuid,$2::uuid,$3::uuid,$4,$5,$6,$7::jsonb,'loop_round',$8,$9,
		     $10::jsonb,$11::jsonb,NULLIF($12,'')::uuid,0,NULL,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
		     now(),now()
		   )`,
		roundID,
		projectID,
		loop.ID,
		nextRound,
		loop.Mode,
		roundPending,
		`{}`,
		loop.ModelArch,
		loop.QueryStrategy,
		paramsJSON,
		resourcesJSON,
		sourceCommitID,
	); err != nil {
		return false, err
	}

	stepSpecs := stepSpecsByMode(loop.Mode)
	previousStepID := ""
	for idx, stepType := range stepSpecs {
		stepID := uuid.NewString()
		dependsOn := []string{}
		if previousStepID != "" {
			dependsOn = append(dependsOn, previousStepID)
		}
		dependsOnJSON, err := marshalJSON(dependsOn)
		if err != nil {
			return false, err
		}
		dispatchKind := "DISPATCHABLE"
		if isOrchestratorStepType(stepType) {
			dispatchKind = "ORCHESTRATOR"
		}
		if _, err := tx.Exec(
			ctx,
			`INSERT INTO step(
				     id,round_id,step_type,dispatch_kind,state,round_index,step_index,depends_on_step_ids,resolved_params,metrics,artifacts,
				     input_commit_id,attempt,max_attempts,state_version,dispatch_request_id,created_at,updated_at
				   ) VALUES (
				     $1::uuid,$2::uuid,$3,$4,'PENDING',$5,$6,$7::jsonb,$8::jsonb,'{}'::jsonb,'{}'::jsonb,
				     NULLIF($9,'')::uuid,1,3,0,NULL,now(),now()
				   )`,
			stepID,
			roundID,
			stepType,
			dispatchKind,
			nextRound,
			idx+1,
			dependsOnJSON,
			paramsJSON,
			sourceCommitID,
		); err != nil {
			return false, err
		}
		previousStepID = stepID
		if idx == 0 {
			s.dispatcher.QueueStep(stepID)
		}
	}

	phase := phaseALTrain
	if loop.Mode == modeSIM {
		phase = phaseSimTrain
	}
	if loop.Mode == modeManual {
		phase = phaseManualTrain
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE loop
		 SET current_iteration=$2,
		     last_round_id=$3::uuid,
		     status='RUNNING',
		     phase=$4,
		     terminal_reason=NULL,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		loop.ID,
		nextRound,
		roundID,
		phase,
	); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) refreshRoundAggregateTx(ctx context.Context, tx pgx.Tx, roundID string) (string, error) {
	rows, err := tx.Query(ctx, `SELECT state,COUNT(*)::int FROM step WHERE round_id=$1::uuid GROUP BY state`, roundID)
	if err != nil {
		return "", err
	}
	counts := map[string]int{}
	total := 0
	for rows.Next() {
		var state string
		var count int
		if err := rows.Scan(&state, &count); err != nil {
			rows.Close()
			return "", err
		}
		counts[state] = count
		total += count
	}
	rows.Close()
	if total == 0 {
		return roundPending, nil
	}

	state := summarizeRoundState(counts, total)
	countsJSON, err := marshalJSON(counts)
	if err != nil {
		return "", err
	}
	if _, err := tx.Exec(
		ctx,
		`UPDATE round
		 SET state=$2::roundstatus,
		     step_counts=$3::jsonb,
		     started_at=CASE WHEN $2::roundstatus='RUNNING'::roundstatus THEN COALESCE(started_at,now()) ELSE started_at END,
		     ended_at=CASE WHEN $2::roundstatus IN ('COMPLETED'::roundstatus,'FAILED'::roundstatus,'CANCELLED'::roundstatus) THEN COALESCE(ended_at,now()) ELSE ended_at END,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		roundID,
		state,
		countsJSON,
	); err != nil {
		return "", err
	}
	return state, nil
}

func summarizeRoundState(counts map[string]int, total int) string {
	if total <= 0 {
		return roundPending
	}
	failed := counts[stepFailed]
	cancelled := counts[stepCancelled]
	running := counts[stepRunning] + counts[stepDispatching] + counts[stepRetrying]
	pending := counts[stepPending] + counts[stepReady]
	succeeded := counts[stepSucceeded] + counts[stepSkipped]

	if failed > 0 {
		return roundFailed
	}
	if running > 0 {
		return roundRunning
	}
	if pending > 0 && succeeded == 0 && cancelled == 0 {
		return roundPending
	}
	if cancelled == total {
		return roundCancelled
	}
	if succeeded == total {
		return roundCompleted
	}
	if pending > 0 {
		return roundRunning
	}
	if cancelled > 0 {
		return roundCancelled
	}
	return roundPending
}

func (s *Service) listPendingStepIDs(ctx context.Context, limit int) ([]string, error) {
	rows, err := s.repo.Pool().Query(
		ctx,
		`SELECT s.id::text
		   FROM step s
		   JOIN round r ON r.id = s.round_id
		   JOIN loop l ON l.id = r.loop_id
		  WHERE s.state='PENDING'
		    AND l.status='RUNNING'
		  ORDER BY s.created_at ASC
		  LIMIT $1`,
		max(1, limit),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ids := make([]string, 0, limit)
	for rows.Next() {
		var stepID string
		if err := rows.Scan(&stepID); err != nil {
			return nil, err
		}
		ids = append(ids, stepID)
	}
	return ids, rows.Err()
}

func (s *Service) dependenciesSatisfiedTx(ctx context.Context, tx pgx.Tx, dependencyIDs []string) (bool, error) {
	if len(dependencyIDs) == 0 {
		return true, nil
	}
	uuids := make([]uuid.UUID, 0, len(dependencyIDs))
	for _, item := range dependencyIDs {
		parsed, err := uuid.Parse(strings.TrimSpace(item))
		if err != nil {
			return false, nil
		}
		uuids = append(uuids, parsed)
	}
	rows, err := tx.Query(
		ctx,
		`SELECT state FROM step WHERE id = ANY($1::uuid[])`,
		uuids,
	)
	if err != nil {
		return false, err
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		count++
		var state string
		if err := rows.Scan(&state); err != nil {
			return false, err
		}
		if state != stepSucceeded {
			return false, nil
		}
	}
	return count == len(dependencyIDs), rows.Err()
}

func (s *Service) markStepDispatchingTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	executorID string,
	requestID string,
) (bool, error) {
	tag, err := tx.Exec(
		ctx,
		`UPDATE step
		 SET state='DISPATCHING',
		     assigned_executor_id=$2,
		     dispatch_request_id=$3,
		     state_version=state_version+1,
		     updated_at=now()
		 WHERE id=$1::uuid AND state='PENDING'`,
		stepID,
		executorID,
		requestID,
	)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

func (s *Service) updateLoopStatus(ctx context.Context, tx pgx.Tx, loopID string, status string) error {
	_, err := tx.Exec(
		ctx,
		`UPDATE loop SET status=$2,updated_at=now() WHERE id=$1::uuid`,
		loopID,
		status,
	)
	return err
}

func (s *Service) updateLoopState(
	ctx context.Context,
	tx pgx.Tx,
	loopID string,
	status string,
	phase string,
	terminalReason string,
	lastConfirmedCommitID string,
) error {
	_, err := tx.Exec(
		ctx,
		`UPDATE loop
		 SET status=$2,
		     phase=$3,
		     terminal_reason=NULLIF($4,''),
		     last_confirmed_commit_id=NULLIF($5,'')::uuid,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		loopID,
		status,
		phase,
		strings.TrimSpace(terminalReason),
		strings.TrimSpace(lastConfirmedCommitID),
	)
	return err
}

func (s *Service) findRoundIDByStep(ctx context.Context, tx pgx.Tx, stepID string) (string, error) {
	var roundID string
	if err := tx.QueryRow(ctx, `SELECT round_id::text FROM step WHERE id=$1::uuid`, stepID).Scan(&roundID); err != nil {
		if err == pgx.ErrNoRows {
			return "", nil
		}
		return "", err
	}
	return roundID, nil
}

func (s *Service) resolveBranchHead(ctx context.Context, branchID string) (headCommitID string, projectID string, err error) {
	if s.domainClient != nil && s.domainClient.Enabled() {
		response, callErr := s.domainClient.GetBranchHead(ctx, branchID)
		if callErr == nil && response.GetFound() {
			return strings.TrimSpace(response.GetHeadCommitId()), strings.TrimSpace(response.GetProjectId()), nil
		}
	}
	if !s.repo.Enabled() {
		return "", "", nil
	}
	err = s.repo.Pool().QueryRow(
		ctx,
		`SELECT COALESCE(head_commit_id::text,''),COALESCE(project_id::text,'')
		   FROM branch
		  WHERE id=$1::uuid`,
		branchID,
	).Scan(&headCommitID, &projectID)
	if err == pgx.ErrNoRows {
		return "", "", nil
	}
	return strings.TrimSpace(headCommitID), strings.TrimSpace(projectID), err
}

func (s *Service) countNewLabels(
	ctx context.Context,
	projectID string,
	branchID string,
	sinceCommitID string,
) (newLabels int64, latestCommitID string, err error) {
	if s.domainClient != nil && s.domainClient.Enabled() {
		response, callErr := s.domainClient.CountNewLabelsSinceCommit(ctx, projectID, branchID, sinceCommitID)
		if callErr == nil {
			return response.GetNewLabelCount(), strings.TrimSpace(response.GetLatestCommitId()), nil
		}
	}
	headCommitID, _, err := s.resolveBranchHead(ctx, branchID)
	if err != nil || headCommitID == "" {
		return 0, "", err
	}
	var latestCount int64
	if err := s.repo.Pool().QueryRow(
		ctx,
		`SELECT COUNT(*)::bigint FROM commit_annotation_map WHERE commit_id=$1::uuid`,
		headCommitID,
	).Scan(&latestCount); err != nil {
		return 0, "", err
	}
	var sinceCount int64
	if strings.TrimSpace(sinceCommitID) != "" {
		if err := s.repo.Pool().QueryRow(
			ctx,
			`SELECT COUNT(*)::bigint FROM commit_annotation_map WHERE commit_id=$1::uuid`,
			sinceCommitID,
		).Scan(&sinceCount); err != nil {
			return 0, "", err
		}
	}
	return max64(0, latestCount-sinceCount), headCommitID, nil
}

func (s *Service) getLatestRoundByLoopTx(ctx context.Context, tx pgx.Tx, loopID string) (roundRow, bool, error) {
	var row roundRow
	if err := tx.QueryRow(
		ctx,
		`SELECT id::text,round_index,COALESCE(state::text,''),ended_at
		   FROM round
		  WHERE loop_id=$1::uuid
		  ORDER BY round_index DESC,created_at DESC
		  LIMIT 1`,
		loopID,
	).Scan(&row.ID, &row.RoundIndex, &row.SummaryStatus, &row.EndedAt); err != nil {
		if err == pgx.ErrNoRows {
			return roundRow{}, false, nil
		}
		return roundRow{}, false, err
	}
	return row, true, nil
}

func (s *Service) lockLoop(ctx context.Context, tx pgx.Tx, loopID string) (loopRow, bool, error) {
	if key, ok := loopAdvisoryKey(loopID); ok {
		var locked bool
		if err := tx.QueryRow(ctx, `SELECT pg_try_advisory_xact_lock($1)`, key).Scan(&locked); err != nil {
			return loopRow{}, false, err
		}
		if !locked {
			return loopRow{}, false, nil
		}
	}

	var row loopRow
	if err := tx.QueryRow(
		ctx,
		`SELECT id::text,
		        project_id::text,
		        branch_id::text,
		        COALESCE(mode::text,''),
		        COALESCE(phase::text,''),
		        COALESCE(status::text,''),
		        current_iteration,
		        max_rounds,
		        query_batch_size,
		        COALESCE(query_strategy,''),
		        COALESCE(model_arch,''),
		        COALESCE(global_config::text,'{}'),
		        COALESCE(last_confirmed_commit_id::text,'')
		   FROM loop
		  WHERE id=$1::uuid
		  FOR UPDATE`,
		loopID,
	).Scan(
		&row.ID,
		&row.ProjectID,
		&row.BranchID,
		&row.Mode,
		&row.Phase,
		&row.Status,
		&row.CurrentIteration,
		&row.MaxRounds,
		&row.QueryBatchSize,
		&row.QueryStrategy,
		&row.ModelArch,
		&row.GlobalConfig,
		&row.LastConfirmedCommitID,
	); err != nil {
		if err == pgx.ErrNoRows {
			return loopRow{}, false, nil
		}
		return loopRow{}, false, err
	}
	return row, true, nil
}

func (s *Service) getStepPayloadByIDTx(ctx context.Context, tx pgx.Tx, stepID string) (stepDispatchPayload, bool, error) {
	var row stepDispatchPayload
	if err := tx.QueryRow(
		ctx,
		`SELECT
			     t.id::text,
			     t.round_id::text,
			     COALESCE(t.state::text,''),
			     COALESCE(t.step_type::text,''),
			     COALESCE(t.dispatch_kind::text,''),
			     t.round_index,
			     t.attempt,
			     COALESCE(t.depends_on_step_ids::text,'[]'),
		     COALESCE(t.resolved_params::text,'{}'),
		     COALESCE(t.input_commit_id::text,''),
		     j.loop_id::text,
		     j.project_id::text,
		     COALESCE(j.plugin_id,''),
		     COALESCE(j.mode::text,''),
		     COALESCE(j.query_strategy,''),
		     COALESCE(j.resolved_params::text,'{}'),
		     COALESCE(j.resources::text,'{}'),
		     COALESCE(j.input_commit_id::text,'')
		   FROM step t
		   JOIN round j ON j.id=t.round_id
		  WHERE t.id=$1::uuid
		  FOR UPDATE`,
		stepID,
	).Scan(
		&row.StepID,
		&row.RoundID,
		&row.Status,
		&row.StepType,
		&row.DispatchKind,
		&row.RoundIndex,
		&row.Attempt,
		&row.dependsOnRaw,
		&row.paramsRaw,
		&row.InputCommitID,
		&row.LoopID,
		&row.ProjectID,
		&row.PluginID,
		&row.Mode,
		&row.QueryStrategy,
		&row.roundParamsRaw,
		&row.resourcesRaw,
		&row.roundInputCommitID,
	); err != nil {
		if err == pgx.ErrNoRows {
			return stepDispatchPayload{}, false, nil
		}
		return stepDispatchPayload{}, false, err
	}
	if strings.TrimSpace(row.InputCommitID) == "" {
		row.InputCommitID = row.roundInputCommitID
	}
	var parseErr error
	row.DependsOnStepIDs, parseErr = parseJSONStrings(row.dependsOnRaw)
	if parseErr != nil {
		return stepDispatchPayload{}, false, parseErr
	}
	row.Params, parseErr = toStruct(row.paramsRaw)
	if parseErr != nil {
		return stepDispatchPayload{}, false, parseErr
	}
	if row.Params == nil || len(row.Params.GetFields()) == 0 {
		row.Params, parseErr = toStruct(row.roundParamsRaw)
		if parseErr != nil {
			return stepDispatchPayload{}, false, parseErr
		}
	}
	row.Resources = toResourceSummary(row.resourcesRaw)
	return row, true, nil
}

func (s *Service) getCommandLogTx(ctx context.Context, tx pgx.Tx, commandID string) (commandLogEntry, bool, error) {
	var row commandLogEntry
	if err := tx.QueryRow(
		ctx,
		`SELECT id::text,COALESCE(status,''),COALESCE(detail,'')
		   FROM runtime_command_log
		  WHERE command_id=$1
		  LIMIT 1`,
		commandID,
	).Scan(&row.ID, &row.Status, &row.Detail); err != nil {
		if err == pgx.ErrNoRows {
			return commandLogEntry{}, false, nil
		}
		return commandLogEntry{}, false, err
	}
	return row, true, nil
}

func (s *Service) insertCommandLogTx(
	ctx context.Context,
	tx pgx.Tx,
	requestID string,
	commandID string,
	commandType string,
	resourceID string,
) (bool, error) {
	tag, err := tx.Exec(
		ctx,
		`INSERT INTO runtime_command_log(id,command_id,command_type,resource_id,status,detail,created_at,updated_at)
		 VALUES($1::uuid,$2,$3,$4,'accepted','accepted',now(),now())
		 ON CONFLICT (command_id) DO NOTHING`,
		requestID,
		commandID,
		commandType,
		resourceID,
	)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

func (s *Service) insertStepEventTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	seq int64,
	ts time.Time,
	eventType string,
	payloadJSON string,
	requestID string,
) (bool, error) {
	tag, err := tx.Exec(
		ctx,
		`INSERT INTO step_event(id,step_id,seq,ts,event_type,payload,request_id,created_at,updated_at)
		 VALUES($1::uuid,$2::uuid,$3,$4,$5,$6::jsonb,NULLIF($7,''),now(),now())
		 ON CONFLICT (step_id,seq) DO NOTHING`,
		uuid.NewString(),
		stepID,
		seq,
		ts,
		eventType,
		payloadJSON,
		requestID,
	)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

func (s *Service) issueCancelAttemptTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	attempt int,
	reason string,
) (bool, error) {
	requestID := uuid.NewString()
	commandID := cancelAttemptCommandID(stepID, attempt)
	inserted, err := s.insertCommandLogTx(ctx, tx, requestID, commandID, "cancel_attempt", stepID)
	if err != nil {
		return false, err
	}
	if !inserted {
		return false, nil
	}

	stopRequestID, accepted := s.dispatcher.StopStep(stepID, reason)
	detail := fmt.Sprintf("cancel attempt issued, accepted=%t, stop_request_id=%s", accepted, strings.TrimSpace(stopRequestID))
	if _, err := tx.Exec(
		ctx,
		`UPDATE runtime_command_log SET status='applied',detail=$2,updated_at=now() WHERE command_id=$1`,
		commandID,
		detail,
	); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) cancelStepIDsTx(
	ctx context.Context,
	tx pgx.Tx,
	stepIDs []string,
	reason string,
) error {
	if len(stepIDs) == 0 {
		return nil
	}
	_, err := tx.Exec(
		ctx,
		`UPDATE step
		    SET state='CANCELLED',
		        last_error=$2,
		        ended_at=COALESCE(ended_at,now()),
		        updated_at=now()
		  WHERE id = ANY($1::uuid[])
		    AND state IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
		stepIDs,
		reason,
	)
	return err
}

func (s *Service) loopHasActiveStepsTx(ctx context.Context, tx pgx.Tx, loopID string) (bool, error) {
	var count int
	if err := tx.QueryRow(
		ctx,
		`SELECT COUNT(*)
		   FROM step t
		   JOIN round j ON j.id=t.round_id
		  WHERE j.loop_id=$1::uuid
		    AND t.state IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
		loopID,
	).Scan(&count); err != nil {
		return false, err
	}
	return count > 0, nil
}

func (s *Service) insertMetricPointsTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	step int,
	epoch *int,
	metrics map[string]float64,
	ts time.Time,
) error {
	if len(metrics) == 0 {
		return nil
	}
	for metricName, metricValue := range metrics {
		cleanMetricName := strings.TrimSpace(metricName)
		if cleanMetricName == "" {
			continue
		}
		if _, err := tx.Exec(
			ctx,
			`INSERT INTO step_metric_point(id,step_id,step,epoch,metric_name,metric_value,ts,created_at,updated_at)
			 VALUES($1::uuid,$2::uuid,$3,$4,$5,$6,$7,now(),now())`,
			uuid.NewString(),
			stepID,
			step,
			epoch,
			cleanMetricName,
			metricValue,
			ts,
		); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) replaceStepCandidatesTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	candidates []*runtimecontrolv1.QueryCandidate,
) error {
	if _, err := tx.Exec(ctx, `DELETE FROM step_candidate_item WHERE step_id=$1::uuid`, stepID); err != nil {
		return err
	}
	for idx, item := range candidates {
		sampleIDText := strings.TrimSpace(item.GetSampleId())
		if sampleIDText == "" {
			continue
		}
		parsedSampleID, err := uuid.Parse(sampleIDText)
		if err != nil {
			continue
		}
		reasonJSON, err := marshalJSON(structToMap(item.GetReason()))
		if err != nil {
			return err
		}
		if _, err := tx.Exec(
			ctx,
			`INSERT INTO step_candidate_item(
			     id,step_id,sample_id,rank,score,reason,prediction_snapshot,created_at,updated_at
			   ) VALUES(
			     $1::uuid,$2::uuid,$3::uuid,$4,$5,$6::jsonb,'{}'::jsonb,now(),now()
			   )`,
			uuid.NewString(),
			stepID,
			parsedSampleID.String(),
			idx+1,
			item.GetScore(),
			reasonJSON,
		); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) mergeArtifactIntoStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	artifact *runtimecontrolv1.ArtifactItem,
) error {
	if artifact == nil {
		return nil
	}
	artifactName := strings.TrimSpace(artifact.GetName())
	if artifactName == "" {
		return nil
	}

	var rawArtifacts string
	if err := tx.QueryRow(
		ctx,
		`SELECT COALESCE(artifacts::text,'{}') FROM step WHERE id=$1::uuid FOR UPDATE`,
		stepID,
	).Scan(&rawArtifacts); err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("step not found: %s", stepID)
		}
		return err
	}
	artifacts, err := parseJSONObject(rawArtifacts)
	if err != nil {
		return err
	}
	artifacts[artifactName] = map[string]any{
		"kind": strings.TrimSpace(artifact.GetKind()),
		"uri":  strings.TrimSpace(artifact.GetUri()),
		"meta": structToMap(artifact.GetMeta()),
	}
	artifactsJSON, err := marshalJSON(artifacts)
	if err != nil {
		return err
	}
	_, err = tx.Exec(
		ctx,
		`UPDATE step SET artifacts=$2::jsonb,updated_at=now() WHERE id=$1::uuid`,
		stepID,
		artifactsJSON,
	)
	return err
}

type loopRow struct {
	ID                    string
	ProjectID             string
	BranchID              string
	Mode                  string
	Phase                 string
	Status                string
	CurrentIteration      int
	MaxRounds             int
	QueryBatchSize        int
	QueryStrategy         string
	ModelArch             string
	GlobalConfig          string
	LastConfirmedCommitID string
}

type roundRow struct {
	ID            string
	RoundIndex    int
	SummaryStatus string
	EndedAt       *time.Time
}

type commandLogEntry struct {
	ID     string
	Status string
	Detail string
}

type stepDispatchPayload struct {
	StepID           string
	RoundID          string
	LoopID           string
	ProjectID        string
	InputCommitID    string
	StepType         string
	DispatchKind     string
	PluginID         string
	Mode             string
	QueryStrategy    string
	RoundIndex       int
	Attempt          int
	Status           string
	DependsOnStepIDs []string
	Params           *structpb.Struct
	Resources        *runtimecontrolv1.ResourceSummary

	dependsOnRaw       string
	paramsRaw          string
	roundParamsRaw     string
	resourcesRaw       string
	roundInputCommitID string
}

func toStruct(raw string) (*structpb.Struct, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		raw = "{}"
	}
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return &structpb.Struct{}, nil
	}
	structPayload, err := structpb.NewStruct(payload)
	if err != nil {
		return &structpb.Struct{}, nil
	}
	return structPayload, nil
}

func marshalJSON(value any) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func marshalArtifacts(items []*runtimecontrolv1.ArtifactItem) (string, error) {
	artifacts := map[string]any{}
	for _, item := range items {
		name := strings.TrimSpace(item.GetName())
		if name == "" {
			continue
		}
		artifacts[name] = map[string]any{
			"kind": strings.TrimSpace(item.GetKind()),
			"uri":  strings.TrimSpace(item.GetUri()),
			"meta": structToMap(item.GetMeta()),
		}
	}
	return marshalJSON(artifacts)
}

func parseJSONObject(raw string) (map[string]any, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return map[string]any{}, nil
	}
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return map[string]any{}, nil
	}
	return payload, nil
}

func structToMap(payload *structpb.Struct) map[string]any {
	if payload == nil {
		return map[string]any{}
	}
	items := payload.AsMap()
	if items == nil {
		return map[string]any{}
	}
	return items
}

func decodeStepEvent(event *runtimecontrolv1.StepEvent) (string, map[string]any, string) {
	if event == nil {
		return "", map[string]any{}, ""
	}
	switch payload := event.GetEventPayload().(type) {
	case *runtimecontrolv1.StepEvent_StatusEvent:
		statusText := runtimeStatusToStepStatus(payload.StatusEvent.GetStatus())
		return "status", map[string]any{
			"status": statusText,
			"reason": strings.TrimSpace(payload.StatusEvent.GetReason()),
		}, statusText
	case *runtimecontrolv1.StepEvent_LogEvent:
		return "log", map[string]any{
			"level":   strings.TrimSpace(payload.LogEvent.GetLevel()),
			"message": payload.LogEvent.GetMessage(),
		}, ""
	case *runtimecontrolv1.StepEvent_ProgressEvent:
		return "progress", map[string]any{
			"epoch":       int(payload.ProgressEvent.GetEpoch()),
			"step":        int(payload.ProgressEvent.GetStep()),
			"total_steps": int(payload.ProgressEvent.GetTotalSteps()),
			"eta_sec":     int(payload.ProgressEvent.GetEtaSec()),
		}, ""
	case *runtimecontrolv1.StepEvent_MetricEvent:
		metrics := map[string]float64{}
		for metricName, metricValue := range payload.MetricEvent.GetMetrics() {
			metrics[metricName] = metricValue
		}
		return "metric", map[string]any{
			"step":    int(payload.MetricEvent.GetStep()),
			"epoch":   int(payload.MetricEvent.GetEpoch()),
			"metrics": metrics,
		}, ""
	case *runtimecontrolv1.StepEvent_ArtifactEvent:
		artifact := payload.ArtifactEvent.GetArtifact()
		if artifact == nil {
			return "artifact", map[string]any{}, ""
		}
		return "artifact", map[string]any{
			"kind": strings.TrimSpace(artifact.GetKind()),
			"name": strings.TrimSpace(artifact.GetName()),
			"uri":  strings.TrimSpace(artifact.GetUri()),
			"meta": structToMap(artifact.GetMeta()),
		}, ""
	default:
		return "log", map[string]any{
			"level":   "WARN",
			"message": "unknown runtime event payload",
		}, ""
	}
}

func stepEventTime(tsMillis int64) time.Time {
	if tsMillis <= 0 {
		return time.Now().UTC()
	}
	return time.UnixMilli(tsMillis).UTC()
}

func ptrInt(value int) *int {
	return &value
}

func parseJSONStrings(raw string) ([]string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return []string{}, nil
	}
	result := []string{}
	if err := json.Unmarshal([]byte(raw), &result); err != nil {
		return []string{}, nil
	}
	cleaned := make([]string, 0, len(result))
	for _, item := range result {
		value := strings.TrimSpace(item)
		if value != "" {
			cleaned = append(cleaned, value)
		}
	}
	return cleaned, nil
}

func toResourceSummary(raw string) *runtimecontrolv1.ResourceSummary {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return &runtimecontrolv1.ResourceSummary{}
	}
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return &runtimecontrolv1.ResourceSummary{}
	}
	summary := &runtimecontrolv1.ResourceSummary{}
	if value, ok := payload["gpu_count"].(float64); ok {
		summary.GpuCount = int32(value)
	}
	if value, ok := payload["cpu_workers"].(float64); ok {
		summary.CpuWorkers = int32(value)
	}
	if value, ok := payload["memory_mb"].(float64); ok {
		summary.MemoryMb = int32(value)
	}
	if ids, ok := payload["gpu_device_ids"].([]any); ok {
		for _, item := range ids {
			if numeric, ok := item.(float64); ok {
				summary.GpuDeviceIds = append(summary.GpuDeviceIds, int32(numeric))
			}
		}
	}
	return summary
}

func stepSpecsByMode(mode string) []string {
	switch mode {
	case modeSIM:
		return []string{"TRAIN", "SCORE", "EVAL", "SELECT", "ACTIVATE_SAMPLES", "ADVANCE_BRANCH"}
	case modeManual:
		return []string{"TRAIN", "EVAL", "EXPORT"}
	default:
		return []string{"TRAIN", "SCORE", "EVAL", "SELECT"}
	}
}

func pluginCapabilitiesToMaps(plugins []*runtimecontrolv1.PluginCapability) []map[string]any {
	items := make([]map[string]any, 0, len(plugins))
	for _, item := range plugins {
		if item == nil {
			continue
		}
		pluginID := strings.TrimSpace(item.GetPluginId())
		if pluginID == "" {
			continue
		}
		supportedAccelerators := make([]string, 0, len(item.GetSupportedAccelerators()))
		for _, accelerator := range item.GetSupportedAccelerators() {
			text := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(accelerator.String(), "ACCELERATOR_TYPE_")))
			if text == "" || text == "unspecified" {
				continue
			}
			supportedAccelerators = append(supportedAccelerators, text)
		}
		items = append(items, map[string]any{
			"plugin_id":              pluginID,
			"display_name":           strings.TrimSpace(item.GetDisplayName()),
			"version":                strings.TrimSpace(item.GetVersion()),
			"supported_step_types":   normalizeStringSlice(item.GetSupportedStepTypes()),
			"supported_strategies":   normalizeStringSlice(item.GetSupportedStrategies()),
			"supported_accelerators": supportedAccelerators,
			"supports_auto_fallback": item.GetSupportsAutoFallback(),
			"request_config_schema":  structToMap(item.GetRequestConfigSchema()),
			"default_request_config": structToMap(item.GetDefaultRequestConfig()),
		})
	}
	return items
}

func resourceSummaryToMap(summary *runtimecontrolv1.ResourceSummary) map[string]any {
	if summary == nil {
		return map[string]any{}
	}
	accelerators := make([]map[string]any, 0, len(summary.GetAccelerators()))
	for _, item := range summary.GetAccelerators() {
		if item == nil {
			continue
		}
		acceleratorType := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(item.GetType().String(), "ACCELERATOR_TYPE_")))
		if acceleratorType == "" {
			acceleratorType = "unspecified"
		}
		accelerators = append(accelerators, map[string]any{
			"type":         acceleratorType,
			"available":    item.GetAvailable(),
			"device_count": item.GetDeviceCount(),
			"device_ids":   normalizeStringSlice(item.GetDeviceIds()),
		})
	}
	gpuDeviceIDs := make([]int32, 0, len(summary.GetGpuDeviceIds()))
	for _, item := range summary.GetGpuDeviceIds() {
		gpuDeviceIDs = append(gpuDeviceIDs, item)
	}
	return map[string]any{
		"gpu_count":      summary.GetGpuCount(),
		"gpu_device_ids": gpuDeviceIDs,
		"cpu_workers":    summary.GetCpuWorkers(),
		"memory_mb":      summary.GetMemoryMb(),
		"accelerators":   accelerators,
	}
}

func normalizeStringSlice(raw []string) []string {
	items := make([]string, 0, len(raw))
	for _, item := range raw {
		value := strings.TrimSpace(item)
		if value == "" {
			continue
		}
		items = append(items, value)
	}
	return items
}

func toRuntimeStepType(raw string) runtimecontrolv1.RuntimeStepType {
	switch strings.ToUpper(strings.TrimSpace(raw)) {
	case "TRAIN":
		return runtimecontrolv1.RuntimeStepType_TRAIN
	case "SCORE":
		return runtimecontrolv1.RuntimeStepType_SCORE
	case "SELECT":
		return runtimecontrolv1.RuntimeStepType_SELECT
	case "ACTIVATE_SAMPLES":
		return runtimecontrolv1.RuntimeStepType_ACTIVATE_SAMPLES
	case "ADVANCE_BRANCH":
		return runtimecontrolv1.RuntimeStepType_ADVANCE_BRANCH
	case "WAIT_ANNOTATION":
		return runtimecontrolv1.RuntimeStepType_WAIT_ANNOTATION
	case "EVAL":
		return runtimecontrolv1.RuntimeStepType_EVAL
	case "EXPORT":
		return runtimecontrolv1.RuntimeStepType_EXPORT
	case "UPLOAD_ARTIFACT":
		return runtimecontrolv1.RuntimeStepType_UPLOAD_ARTIFACT
	default:
		return runtimecontrolv1.RuntimeStepType_RUNTIME_STEP_TYPE_UNSPECIFIED
	}
}

func toRuntimeStepDispatchKind(raw string) runtimecontrolv1.RuntimeStepDispatchKind {
	switch strings.ToUpper(strings.TrimSpace(raw)) {
	case "DISPATCHABLE":
		return runtimecontrolv1.RuntimeStepDispatchKind_DISPATCHABLE
	case "ORCHESTRATOR":
		return runtimecontrolv1.RuntimeStepDispatchKind_ORCHESTRATOR
	default:
		return runtimecontrolv1.RuntimeStepDispatchKind_RUNTIME_STEP_DISPATCH_KIND_UNSPECIFIED
	}
}

func toRuntimeLoopMode(raw string) runtimecontrolv1.RuntimeLoopMode {
	switch strings.ToUpper(strings.TrimSpace(raw)) {
	case modeAL:
		return runtimecontrolv1.RuntimeLoopMode_ACTIVE_LEARNING
	case modeSIM:
		return runtimecontrolv1.RuntimeLoopMode_SIMULATION
	case modeManual:
		return runtimecontrolv1.RuntimeLoopMode_MANUAL
	default:
		return runtimecontrolv1.RuntimeLoopMode_RUNTIME_LOOP_MODE_UNSPECIFIED
	}
}

func runtimeStatusToStepStatus(status runtimecontrolv1.RuntimeStepStatus) string {
	switch status {
	case runtimecontrolv1.RuntimeStepStatus_PENDING:
		return stepPending
	case runtimecontrolv1.RuntimeStepStatus_DISPATCHING:
		return stepDispatching
	case runtimecontrolv1.RuntimeStepStatus_RUNNING:
		return stepRunning
	case runtimecontrolv1.RuntimeStepStatus_RETRYING:
		return stepRetrying
	case runtimecontrolv1.RuntimeStepStatus_SUCCEEDED:
		return stepSucceeded
	case runtimecontrolv1.RuntimeStepStatus_FAILED:
		return stepFailed
	case runtimecontrolv1.RuntimeStepStatus_CANCELLED:
		return stepCancelled
	case runtimecontrolv1.RuntimeStepStatus_SKIPPED:
		return stepSkipped
	default:
		return ""
	}
}

func extractOracleCommitID(rawConfig string) string {
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(rawConfig), &payload); err != nil {
		return ""
	}
	simulationRaw, ok := payload["simulation"]
	if !ok {
		return ""
	}
	simulationMap, ok := simulationRaw.(map[string]any)
	if !ok {
		return ""
	}
	return strings.TrimSpace(fmt.Sprintf("%v", simulationMap["oracle_commit_id"]))
}

func extractRoundResources(rawConfig string) map[string]any {
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(rawConfig), &payload); err != nil {
		return nil
	}
	resourcesRaw, ok := payload["round_resources_default"]
	if !ok {
		return nil
	}
	resources, ok := resourcesRaw.(map[string]any)
	if !ok {
		return nil
	}
	return resources
}

func activationCommandID(stepPayload stepDispatchPayload) string {
	raw := fmt.Sprintf(
		"%s:%d:%s:%d:%s",
		strings.TrimSpace(stepPayload.LoopID),
		stepPayload.RoundIndex,
		strings.TrimSpace(stepPayload.StepID),
		stepPayload.Attempt,
		strings.TrimSpace(stepPayload.InputCommitID),
	)
	sum := sha256.Sum256([]byte(raw))
	return "activate_samples:" + hex.EncodeToString(sum[:])
}

func advanceBranchCommandID(stepPayload stepDispatchPayload, commitID string) string {
	raw := fmt.Sprintf(
		"%s:%d:%s:%d:%s",
		strings.TrimSpace(stepPayload.LoopID),
		stepPayload.RoundIndex,
		strings.TrimSpace(stepPayload.StepID),
		stepPayload.Attempt,
		strings.TrimSpace(commitID),
	)
	sum := sha256.Sum256([]byte(raw))
	return "advance_branch:" + hex.EncodeToString(sum[:])
}

func cancelAttemptCommandID(stepID string, attempt int) string {
	raw := fmt.Sprintf("%s:%d", strings.TrimSpace(stepID), max(1, attempt))
	sum := sha256.Sum256([]byte(raw))
	return "cancel_attempt:" + hex.EncodeToString(sum[:])
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func loopAdvisoryKey(loopID string) (int64, bool) {
	parsed, err := uuid.Parse(strings.TrimSpace(loopID))
	if err != nil {
		return 0, false
	}
	value := int64(0)
	for i := 0; i < 8; i++ {
		value = (value << 8) | int64(parsed[i])
	}
	if value < 0 {
		value = -value
	}
	if value == 0 {
		value = 1
	}
	return value, true
}
