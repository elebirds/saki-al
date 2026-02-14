package controlplane

import (
	"context"
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
	phaseALWaitAnnotation = "AL_WAIT_ANNOTATION"
	phaseALEval           = "AL_EVAL"
	phaseSimTrain         = "SIM_TRAIN"
	phaseSimEval          = "SIM_EVAL"
	phaseManualTaskRun    = "MANUAL_TASK_RUNNING"
	phaseManualWait       = "MANUAL_WAIT_CONFIRM"
	phaseManualFinalize   = "MANUAL_FINALIZE"

	modeAL     = "ACTIVE_LEARNING"
	modeSIM    = "SIMULATION"
	modeManual = "MANUAL"

	jobPending       = "JOB_PENDING"
	jobRunning       = "JOB_RUNNING"
	jobPartialFailed = "JOB_PARTIAL_FAILED"
	jobFailed        = "JOB_FAILED"
	jobSucceeded     = "JOB_SUCCEEDED"
	jobCancelled     = "JOB_CANCELLED"

	taskPending     = "PENDING"
	taskDispatching = "DISPATCHING"
	taskRunning     = "RUNNING"
	taskRetrying    = "RETRYING"
	taskSucceeded   = "SUCCEEDED"
	taskFailed      = "FAILED"
	taskCancelled   = "CANCELLED"
	taskSkipped     = "SKIPPED"
)

var terminalJobStatuses = map[string]struct{}{
	jobSucceeded:     {},
	jobFailed:        {},
	jobPartialFailed: {},
	jobCancelled:     {},
}

type CommandResult struct {
	CommandID string
	Status    string
	Message   string
	RequestID string
}

type Service struct {
	repo            *repo.RuntimeRepo
	dispatcher      *dispatch.Dispatcher
	domainClient    *runtime_domain_client.Client
	dispatchLockKey int64
	simCooldown     time.Duration
	logger          zerolog.Logger
}

func NewService(
	repository *repo.RuntimeRepo,
	dispatcher *dispatch.Dispatcher,
	domainClient *runtime_domain_client.Client,
	dispatchLockKey int64,
	simulationCooldownSec int,
	logger zerolog.Logger,
) *Service {
	if simulationCooldownSec < 0 {
		simulationCooldownSec = 0
	}
	return &Service{
		repo:            repository,
		dispatcher:      dispatcher,
		domainClient:    domainClient,
		dispatchLockKey: dispatchLockKey,
		simCooldown:     time.Duration(simulationCooldownSec) * time.Second,
		logger:          logger,
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
		if loop.Status == statusCompleted {
			return "rejected", "completed loop cannot be started", nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasJob(ctx, tx, loop, commandID); err != nil {
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
		if loop.Status == statusStopped || loop.Status == statusCompleted {
			return "rejected", fmt.Sprintf("loop in status %s cannot be resumed", loop.Status), nil
		}
		if err := s.updateLoopStatus(ctx, tx, loop.ID, statusRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasJob(ctx, tx, loop, commandID); err != nil {
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
			if loop.CurrentIteration >= loop.MaxRounds {
				if err := s.updateLoopState(ctx, tx, loop.ID, statusCompleted, phaseALEval, "", loop.LastConfirmedCommitID); err != nil {
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

			created, err := s.createNextJobTx(ctx, tx, loop, commandID)
			if err != nil {
				return "", "", err
			}
			if !created {
				return "rejected", "cannot create next job for active-learning loop", nil
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
	return s.StopJob(ctx, commandID, roundID, reason)
}

func (s *Service) StopJob(ctx context.Context, commandID string, jobID string, reason string) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}
	return s.withCommand(ctx, commandID, "stop_job", jobID, func(tx pgx.Tx, _ string) (string, string, error) {
		var currentStatus string
		if err := tx.QueryRow(
			ctx,
			`SELECT COALESCE(summary_status::text,'') FROM job WHERE id=$1::uuid`,
			jobID,
		).Scan(&currentStatus); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return "rejected", "job not found", nil
			}
			return "", "", err
		}
		if _, ok := terminalJobStatuses[currentStatus]; ok {
			return "applied", "job already in terminal state", nil
		}

		if _, err := tx.Exec(
			ctx,
			`UPDATE job SET summary_status=$2,last_error=$3,updated_at=now() WHERE id=$1::uuid`,
			jobID,
			jobCancelled,
			reason,
		); err != nil {
			return "", "", err
		}
		rows, err := tx.Query(
			ctx,
			`SELECT id::text FROM job_task
				 WHERE job_id=$1::uuid
				   AND status IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
			jobID,
		)
		if err != nil {
			return "", "", err
		}
		taskIDs := make([]string, 0, 16)
		for rows.Next() {
			var taskID string
			if scanErr := rows.Scan(&taskID); scanErr != nil {
				rows.Close()
				return "", "", scanErr
			}
			taskIDs = append(taskIDs, taskID)
		}
		rows.Close()
		if _, err := tx.Exec(
			ctx,
			`UPDATE job_task
				 SET status='CANCELLED',last_error=$2,ended_at=COALESCE(ended_at,now()),updated_at=now()
				 WHERE job_id=$1::uuid
				   AND status IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
			jobID,
			reason,
		); err != nil {
			return "", "", err
		}
		for _, taskID := range taskIDs {
			s.dispatcher.StopTask(taskID, reason)
		}
		return "applied", "stop_job applied", nil
	})
}

func (s *Service) StopStep(ctx context.Context, commandID string, stepID string, reason string) (CommandResult, error) {
	return s.StopTask(ctx, commandID, stepID, reason)
}

func (s *Service) StopTask(ctx context.Context, commandID string, taskID string, reason string) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}
	return s.withCommand(ctx, commandID, "stop_task", taskID, func(tx pgx.Tx, _ string) (string, string, error) {
		var currentStatus string
		if err := tx.QueryRow(
			ctx,
			`SELECT COALESCE(status::text,'') FROM job_task WHERE id=$1::uuid`,
			taskID,
		).Scan(&currentStatus); err != nil {
			if err == pgx.ErrNoRows {
				return "rejected", "task not found", nil
			}
			return "", "", err
		}
		if currentStatus == taskSucceeded || currentStatus == taskFailed || currentStatus == taskCancelled || currentStatus == taskSkipped {
			return "applied", "task already in terminal state", nil
		}

		if _, err := tx.Exec(
			ctx,
			`UPDATE job_task
			 SET status='CANCELLED',last_error=$2,ended_at=COALESCE(ended_at,now()),updated_at=now()
			 WHERE id=$1::uuid`,
			taskID,
			reason,
		); err != nil {
			return "", "", err
		}
		s.dispatcher.StopTask(taskID, reason)
		return "applied", "stop_task applied", nil
	})
}

func (s *Service) TriggerDispatch(ctx context.Context, commandID string, taskID string) (CommandResult, error) {
	taskID = strings.TrimSpace(taskID)
	return s.withCommand(ctx, commandID, "trigger_dispatch", taskID, func(tx pgx.Tx, _ string) (string, string, error) {
		if taskID != "" {
			dispatched, err := s.dispatchTaskByID(ctx, taskID)
			if err != nil {
				return "", "", err
			}
			if !dispatched {
				return "applied", "task not dispatched", nil
			}
			return "applied", "task dispatched", nil
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
		     id,executor_id,version,status,is_online,current_task_id,plugin_ids,resources,last_seen_at,last_error,created_at,updated_at
		   ) VALUES(
		     $1::uuid,$2,$3,'idle',TRUE,NULL,$4::jsonb,$5::jsonb,now(),NULL,now(),now()
		   )
		   ON CONFLICT (executor_id) DO UPDATE SET
		     version=EXCLUDED.version,
		     status='idle',
		     is_online=TRUE,
		     current_task_id=NULL,
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
	currentTaskID := strings.TrimSpace(heartbeat.GetCurrentTaskId())
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(heartbeat.GetResources()))
	if err != nil {
		return err
	}

	_, err = s.repo.Pool().Exec(
		ctx,
		`INSERT INTO runtime_executor(
		     id,executor_id,version,status,is_online,current_task_id,plugin_ids,resources,last_seen_at,last_error,created_at,updated_at
		   ) VALUES(
		     $1::uuid,$2,'',$3,TRUE,NULLIF($4,''),'{}'::jsonb,$5::jsonb,now(),NULL,now(),now()
		   )
		   ON CONFLICT (executor_id) DO UPDATE SET
		     status=EXCLUDED.status,
		     is_online=TRUE,
		     current_task_id=EXCLUDED.current_task_id,
		     resources=EXCLUDED.resources,
		     last_seen_at=EXCLUDED.last_seen_at,
		     last_error=NULL,
		     updated_at=now()`,
		uuid.NewString(),
		executorID,
		status,
		currentTaskID,
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
		     current_task_id=NULL,
		     last_error=NULLIF($2,''),
		     last_seen_at=now(),
		     updated_at=now()
		 WHERE executor_id=$1`,
		executorID,
		strings.TrimSpace(reason),
	)
	return err
}

func (s *Service) OnTaskEvent(ctx context.Context, event *runtimecontrolv1.TaskEvent) error {
	if !s.repo.Enabled() || event == nil {
		return nil
	}
	taskID := strings.TrimSpace(event.GetTaskId())
	if taskID == "" {
		return nil
	}

	eventType, eventPayload, statusText := decodeTaskEvent(event)
	if eventType == "" {
		return nil
	}
	payloadJSON, err := marshalJSON(eventPayload)
	if err != nil {
		return err
	}
	eventTS := taskEventTime(event.GetTs())

	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	if inserted, err := s.insertTaskEventTx(
		ctx,
		tx,
		taskID,
		event.GetSeq(),
		eventTS,
		eventType,
		payloadJSON,
		strings.TrimSpace(event.GetRequestId()),
	); err != nil {
		return err
	} else if !inserted {
		// Duplicate event by (task_id, seq), skip side effects.
		return tx.Commit(ctx)
	}

	switch eventType {
	case "status":
		statusDB := statusText
		tag, err := tx.Exec(
			ctx,
			`UPDATE job_task
			 SET status=$2::jobtaskstatus,
			     started_at=CASE WHEN $2::jobtaskstatus='RUNNING'::jobtaskstatus THEN COALESCE(started_at,now()) ELSE started_at END,
			     ended_at=CASE WHEN $2::jobtaskstatus IN ('SUCCEEDED'::jobtaskstatus,'FAILED'::jobtaskstatus,'CANCELLED'::jobtaskstatus,'SKIPPED'::jobtaskstatus) THEN COALESCE(ended_at,now()) ELSE ended_at END,
			     last_error=CASE WHEN $2::jobtaskstatus IN ('SUCCEEDED'::jobtaskstatus,'FAILED'::jobtaskstatus,'CANCELLED'::jobtaskstatus,'SKIPPED'::jobtaskstatus) THEN NULLIF($3,'') ELSE last_error END,
			     updated_at=now()
			 WHERE id=$1::uuid`,
			taskID,
			statusDB,
			strings.TrimSpace(event.GetStatusEvent().GetReason()),
		)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return fmt.Errorf("task not found: %s", taskID)
		}

	case "metric":
		metricPayload := event.GetMetricEvent()
		if metricPayload != nil {
			if err := s.insertMetricPointsTx(
				ctx,
				tx,
				taskID,
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
			if err := s.mergeArtifactIntoTaskTx(ctx, tx, taskID, artifactPayload.GetArtifact()); err != nil {
				return err
			}
		}
	}

	jobID, err := s.findJobIDByTask(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if jobID != "" {
		if _, err := s.refreshJobAggregateTx(ctx, tx, jobID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Service) OnTaskResult(ctx context.Context, result *runtimecontrolv1.TaskResult) error {
	if !s.repo.Enabled() || result == nil {
		return nil
	}
	taskID := strings.TrimSpace(result.GetTaskId())
	if taskID == "" {
		return nil
	}
	statusText := runtimeStatusToTaskStatus(result.GetStatus())
	if statusText == "" {
		statusText = taskFailed
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
		`UPDATE job_task
		 SET status=$2::jobtaskstatus,
		     metrics=$3::jsonb,
		     artifacts=$4::jsonb,
		     last_error=NULLIF($5,''),
		     started_at=COALESCE(started_at,now()),
		     ended_at=CASE WHEN $2::jobtaskstatus IN ('SUCCEEDED'::jobtaskstatus,'FAILED'::jobtaskstatus,'CANCELLED'::jobtaskstatus,'SKIPPED'::jobtaskstatus) THEN COALESCE(ended_at,now()) ELSE ended_at END,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		taskID,
		statusDB,
		metricsJSON,
		artifactsJSON,
		strings.TrimSpace(result.GetErrorMessage()),
	)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("task not found: %s", taskID)
	}

	if err := s.replaceTaskCandidatesTx(ctx, tx, taskID, result.GetCandidates()); err != nil {
		return err
	}
	if err := s.insertMetricPointsTx(ctx, tx, taskID, 0, nil, result.GetMetrics(), time.Now().UTC()); err != nil {
		return err
	}

	jobID, err := s.findJobIDByTask(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if jobID != "" {
		if _, err := s.refreshJobAggregateTx(ctx, tx, jobID); err != nil {
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
	latestJob, hasJob, err := s.getLatestJobByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return err
	}
	if !hasJob {
		_, err := s.createNextJobTx(ctx, tx, loop, uuid.NewString())
		return err
	}

	jobStatus, err := s.refreshJobAggregateTx(ctx, tx, latestJob.ID)
	if err != nil {
		return err
	}
	if _, ok := terminalJobStatuses[jobStatus]; !ok {
		return nil
	}

	if jobStatus == jobFailed || jobStatus == jobCancelled || jobStatus == jobPartialFailed {
		if err := s.updateLoopState(ctx, tx, loop.ID, statusFailed, loop.Phase, "job terminal failure", loop.LastConfirmedCommitID); err != nil {
			return err
		}
		return nil
	}

	switch loop.Mode {
	case modeSIM:
		if loop.CurrentIteration >= loop.MaxRounds {
			if err := s.updateLoopState(ctx, tx, loop.ID, statusCompleted, phaseSimEval, "", loop.LastConfirmedCommitID); err != nil {
				return err
			}
		} else {
			if s.shouldDelaySimulationRound(latestJob.EndedAt) {
				return nil
			}
			if _, err := s.createNextJobTx(ctx, tx, loop, uuid.NewString()); err != nil {
				return err
			}
		}
	case modeAL:
		if loop.CurrentIteration >= loop.MaxRounds {
			if err := s.updateLoopState(ctx, tx, loop.ID, statusCompleted, phaseALEval, "", loop.LastConfirmedCommitID); err != nil {
				return err
			}
		} else if err := s.updateLoopState(ctx, tx, loop.ID, statusRunning, phaseALWaitAnnotation, "", loop.LastConfirmedCommitID); err != nil {
			return err
		}
	case modeManual:
		if err := s.updateLoopState(ctx, tx, loop.ID, statusCompleted, phaseManualFinalize, "", loop.LastConfirmedCommitID); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) processStoppingLoopTx(ctx context.Context, tx pgx.Tx, loop loopRow) error {
	rows, err := tx.Query(
		ctx,
		`SELECT t.id::text
		   FROM job_task t
		   JOIN job j ON j.id=t.job_id
		  WHERE j.loop_id=$1::uuid
		    AND t.status IN ('PENDING','DISPATCHING','RUNNING','RETRYING')
		  ORDER BY t.created_at ASC`,
		loop.ID,
	)
	if err != nil {
		return err
	}
	taskIDs := make([]string, 0)
	for rows.Next() {
		var taskID string
		if err := rows.Scan(&taskID); err != nil {
			rows.Close()
			return err
		}
		taskIDs = append(taskIDs, taskID)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	if len(taskIDs) > 0 {
		reason := "loop stopping requested"
		if _, err := tx.Exec(
			ctx,
			`UPDATE job_task
			    SET status='CANCELLED',
			        last_error=$2,
			        ended_at=COALESCE(ended_at,now()),
			        updated_at=now()
			  WHERE id = ANY($1::uuid[])
			    AND status IN ('PENDING','DISPATCHING','RUNNING','RETRYING')`,
			taskIDs,
			reason,
		); err != nil {
			return err
		}
		for _, taskID := range taskIDs {
			s.dispatcher.StopTask(taskID, reason)
		}
		return tx.Commit(ctx)
	}

	if err := s.updateLoopStatus(ctx, tx, loop.ID, statusStopped); err != nil {
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
	for _, queuedTaskID := range s.dispatcher.DrainQueuedTaskIDs() {
		dispatched, err := s.dispatchTaskByID(ctx, queuedTaskID)
		if err != nil {
			return count, err
		}
		if dispatched {
			count++
		}
	}

	taskIDs, err := s.listPendingTaskIDs(ctx, limit)
	if err != nil {
		return count, err
	}
	for _, taskID := range taskIDs {
		dispatched, err := s.dispatchTaskByID(ctx, taskID)
		if err != nil {
			return count, err
		}
		if dispatched {
			count++
		}
	}
	return count, nil
}

func (s *Service) dispatchTaskByID(ctx context.Context, taskID string) (bool, error) {
	tx, err := s.repo.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	task, ok, err := s.getTaskPayloadByIDTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !ok || task.Status != taskPending {
		return false, tx.Commit(ctx)
	}

	depsOK, err := s.dependenciesSatisfiedTx(ctx, tx, task.DependsOnTaskIDs)
	if err != nil {
		return false, err
	}
	if !depsOK {
		return false, tx.Commit(ctx)
	}
	if isOrchestratorTaskType(task.TaskType) {
		executed, err := s.executeOrchestratorTaskTx(ctx, tx, task)
		if err != nil {
			return false, err
		}
		return executed, tx.Commit(ctx)
	}

	executorID, found := s.dispatcher.PickExecutor(task.PluginID)
	if !found {
		return false, tx.Commit(ctx)
	}
	requestID := uuid.NewString()
	updated, err := s.markTaskDispatchingTx(ctx, tx, task.TaskID, executorID, requestID)
	if err != nil {
		return false, err
	}
	if !updated {
		return false, tx.Commit(ctx)
	}

	message := &runtimecontrolv1.TaskPayload{
		TaskId:           task.TaskID,
		JobId:            task.JobID,
		LoopId:           task.LoopID,
		ProjectId:        task.ProjectID,
		SourceCommitId:   task.SourceCommitID,
		TaskType:         toRuntimeTaskType(task.TaskType),
		PluginId:         task.PluginID,
		Mode:             toRuntimeLoopMode(task.Mode),
		QueryStrategy:    task.QueryStrategy,
		Params:           task.Params,
		Resources:        task.Resources,
		RoundIndex:       int32(task.RoundIndex),
		Attempt:          int32(task.Attempt),
		DependsOnTaskIds: task.DependsOnTaskIDs,
	}
	if !s.dispatcher.DispatchTask(executorID, requestID, message) {
		if _, err := tx.Exec(
			ctx,
			`UPDATE job_task SET status='PENDING',assigned_executor_id=NULL,last_error='dispatcher queue full',updated_at=now() WHERE id=$1::uuid`,
			task.TaskID,
		); err != nil {
			return false, err
		}
		return false, tx.Commit(ctx)
	}
	return true, tx.Commit(ctx)
}

func isOrchestratorTaskType(taskType string) bool {
	switch strings.ToUpper(strings.TrimSpace(taskType)) {
	case "ACTIVATE_SAMPLES":
		return true
	default:
		return false
	}
}

func (s *Service) executeOrchestratorTaskTx(
	ctx context.Context,
	tx pgx.Tx,
	task taskDispatchPayload,
) (bool, error) {
	started, err := tx.Exec(
		ctx,
		`UPDATE job_task
		    SET status='RUNNING',
		        started_at=COALESCE(started_at,now()),
		        updated_at=now()
		  WHERE id=$1::uuid
		    AND status='PENDING'`,
		task.TaskID,
	)
	if err != nil {
		return false, err
	}
	if started.RowsAffected() == 0 {
		return false, nil
	}

	resultStatus := taskSucceeded
	lastError := ""
	resultCommitID := ""
	if err := s.runOrchestratorTaskTx(ctx, tx, task, &resultCommitID); err != nil {
		resultStatus = taskFailed
		lastError = err.Error()
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE job_task
		    SET status=$2::jobtaskstatus,
		        last_error=NULLIF($3,''),
		        result_commit_id=NULLIF($4,'')::uuid,
		        ended_at=COALESCE(ended_at,now()),
		        updated_at=now()
		  WHERE id=$1::uuid`,
		task.TaskID,
		resultStatus,
		lastError,
		resultCommitID,
	); err != nil {
		return false, err
	}

	if strings.TrimSpace(resultCommitID) != "" {
		if _, err := tx.Exec(
			ctx,
			`UPDATE job
			    SET result_commit_id=NULLIF($2,'')::uuid,
			        updated_at=now()
			  WHERE id=$1::uuid`,
			task.JobID,
			resultCommitID,
		); err != nil {
			return false, err
		}
	}

	if _, err := s.refreshJobAggregateTx(ctx, tx, task.JobID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) runOrchestratorTaskTx(
	ctx context.Context,
	tx pgx.Tx,
	task taskDispatchPayload,
	resultCommitID *string,
) error {
	switch strings.ToUpper(strings.TrimSpace(task.TaskType)) {
	case "ACTIVATE_SAMPLES":
		return s.runActivateSamplesTx(ctx, tx, task, resultCommitID)
	default:
		return nil
	}
}

func (s *Service) runActivateSamplesTx(
	ctx context.Context,
	tx pgx.Tx,
	task taskDispatchPayload,
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
		task.LoopID,
	).Scan(&projectID, &branchID, &queryStrategy, &globalConfig, &queryBatch); err != nil {
		return err
	}

	oracleCommitID := extractOracleCommitID(globalConfig)
	if oracleCommitID == "" {
		return nil
	}

	sourceCommitID := strings.TrimSpace(task.SourceCommitID)
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

	commandID := uuid.NewString()
	response, err := s.domainClient.ActivateSamples(ctx, &runtimedomainv1.ActivateSamplesRequest{
		CommandId:      commandID,
		ProjectId:      projectID,
		BranchId:       branchID,
		OracleCommitId: oracleCommitID,
		SourceCommitId: sourceCommitID,
		LoopId:         task.LoopID,
		RoundIndex:     int32(task.RoundIndex),
		QueryStrategy:  queryStrategy,
		Topk:           int32(queryBatch),
	})
	if err != nil {
		return err
	}
	commitID := strings.TrimSpace(response.GetCommitId())
	if response.GetCreated() && commitID != "" {
		if _, err := s.domainClient.AdvanceBranchHead(ctx, commandID, branchID, commitID, "simulation activate samples"); err != nil {
			return err
		}
		if resultCommitID != nil {
			*resultCommitID = commitID
		}
	}
	return nil
}

func (s *Service) ensureLoopHasJob(ctx context.Context, tx pgx.Tx, loop loopRow, commandID string) (bool, error) {
	latestJob, hasJob, err := s.getLatestJobByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return false, err
	}
	if !hasJob {
		return s.createNextJobTx(ctx, tx, loop, commandID)
	}
	if _, ok := terminalJobStatuses[latestJob.SummaryStatus]; ok && loop.Mode == modeSIM {
		return s.createNextJobTx(ctx, tx, loop, commandID)
	}
	return false, nil
}

func (s *Service) createNextJobTx(ctx context.Context, tx pgx.Tx, loop loopRow, commandID string) (bool, error) {
	if loop.CurrentIteration >= loop.MaxRounds {
		return false, nil
	}
	nextRound := loop.CurrentIteration + 1
	sourceCommitID, projectIDFromBranch, err := s.resolveBranchHead(ctx, loop.BranchID)
	if err != nil {
		s.logger.Warn().Err(err).Str("loop_id", loop.ID).Msg("resolve branch head failed, continue with empty source commit")
	}
	projectID := loop.ProjectID
	if projectIDFromBranch != "" {
		projectID = projectIDFromBranch
	}

	jobID := uuid.NewString()
	paramsJSON, err := marshalJSON(map[string]any{
		"round_index":    nextRound,
		"loop_mode":      loop.Mode,
		"query_strategy": loop.QueryStrategy,
	})
	if err != nil {
		return false, err
	}
	resourcesJSON := "{}"
	if resourcePayload := extractJobResources(loop.GlobalConfig); resourcePayload != nil {
		if resourcesJSON, err = marshalJSON(resourcePayload); err != nil {
			return false, err
		}
	}

	if _, err := tx.Exec(
		ctx,
		`INSERT INTO job(
		     id,project_id,loop_id,round_index,mode,summary_status,task_counts,job_type,plugin_id,query_strategy,
		     params,resources,source_commit_id,retry_count,last_error,final_metrics,final_artifacts,strategy_params,
		     created_at,updated_at
		   ) VALUES (
		     $1::uuid,$2::uuid,$3::uuid,$4,$5,$6,$7::jsonb,'loop_job',$8,$9,
		     $10::jsonb,$11::jsonb,NULLIF($12,'')::uuid,0,NULL,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb,
		     now(),now()
		   )`,
		jobID,
		projectID,
		loop.ID,
		nextRound,
		loop.Mode,
		jobPending,
		`{}`,
		loop.ModelArch,
		loop.QueryStrategy,
		paramsJSON,
		resourcesJSON,
		sourceCommitID,
	); err != nil {
		return false, err
	}

	taskSpecs := taskSpecsByMode(loop.Mode)
	previousTaskID := ""
	for idx, taskType := range taskSpecs {
		taskID := uuid.NewString()
		dependsOn := []string{}
		if previousTaskID != "" {
			dependsOn = append(dependsOn, previousTaskID)
		}
		dependsOnJSON, err := marshalJSON(dependsOn)
		if err != nil {
			return false, err
		}
		if _, err := tx.Exec(
			ctx,
			`INSERT INTO job_task(
				     id,job_id,task_type,status,round_index,task_index,depends_on,params,metrics,artifacts,
				     source_commit_id,attempt,max_attempts,state_version,dispatch_request_id,created_at,updated_at
				   ) VALUES (
				     $1::uuid,$2::uuid,$3,'PENDING',$4,$5,$6::jsonb,$7::jsonb,'{}'::jsonb,'{}'::jsonb,
				     NULLIF($8,'')::uuid,1,3,0,NULL,now(),now()
				   )`,
			taskID,
			jobID,
			taskType,
			nextRound,
			idx+1,
			dependsOnJSON,
			paramsJSON,
			sourceCommitID,
		); err != nil {
			return false, err
		}
		previousTaskID = taskID
		if idx == 0 {
			s.dispatcher.QueueTask(taskID)
		}
	}

	phase := phaseALTrain
	if loop.Mode == modeSIM {
		phase = phaseSimTrain
	}
	if loop.Mode == modeManual {
		phase = phaseManualTaskRun
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE loop
		 SET current_iteration=$2,
		     last_job_id=$3::uuid,
		     status='RUNNING',
		     phase=$4,
		     last_error=NULL,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		loop.ID,
		nextRound,
		jobID,
		phase,
	); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) refreshJobAggregateTx(ctx context.Context, tx pgx.Tx, jobID string) (string, error) {
	rows, err := tx.Query(ctx, `SELECT status,COUNT(*)::int FROM job_task WHERE job_id=$1::uuid GROUP BY status`, jobID)
	if err != nil {
		return "", err
	}
	counts := map[string]int{}
	total := 0
	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			rows.Close()
			return "", err
		}
		counts[status] = count
		total += count
	}
	rows.Close()
	if total == 0 {
		return jobPending, nil
	}

	status := summarizeJobStatus(counts, total)
	countsJSON, err := marshalJSON(counts)
	if err != nil {
		return "", err
	}
	if _, err := tx.Exec(
		ctx,
		`UPDATE job
		 SET summary_status=$2::jobstatusv2,
		     task_counts=$3::jsonb,
		     started_at=CASE WHEN $2::jobstatusv2='JOB_RUNNING'::jobstatusv2 THEN COALESCE(started_at,now()) ELSE started_at END,
		     ended_at=CASE WHEN $2::jobstatusv2 IN ('JOB_SUCCEEDED'::jobstatusv2,'JOB_FAILED'::jobstatusv2,'JOB_PARTIAL_FAILED'::jobstatusv2,'JOB_CANCELLED'::jobstatusv2) THEN COALESCE(ended_at,now()) ELSE ended_at END,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		jobID,
		status,
		countsJSON,
	); err != nil {
		return "", err
	}
	return status, nil
}

func summarizeJobStatus(counts map[string]int, total int) string {
	if total <= 0 {
		return jobPending
	}
	failed := counts[taskFailed]
	cancelled := counts[taskCancelled]
	running := counts[taskRunning] + counts[taskDispatching] + counts[taskRetrying]
	pending := counts[taskPending]
	succeeded := counts[taskSucceeded] + counts[taskSkipped]

	if failed > 0 {
		if succeeded > 0 || cancelled > 0 {
			return jobPartialFailed
		}
		return jobFailed
	}
	if running > 0 {
		return jobRunning
	}
	if pending > 0 && succeeded == 0 && cancelled == 0 {
		return jobPending
	}
	if cancelled == total {
		return jobCancelled
	}
	if succeeded == total {
		return jobSucceeded
	}
	if cancelled > 0 && succeeded > 0 {
		return jobPartialFailed
	}
	if pending > 0 {
		return jobRunning
	}
	return jobPending
}

func (s *Service) listPendingTaskIDs(ctx context.Context, limit int) ([]string, error) {
	rows, err := s.repo.Pool().Query(
		ctx,
		`SELECT id::text FROM job_task WHERE status='PENDING' ORDER BY created_at ASC LIMIT $1`,
		max(1, limit),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ids := make([]string, 0, limit)
	for rows.Next() {
		var taskID string
		if err := rows.Scan(&taskID); err != nil {
			return nil, err
		}
		ids = append(ids, taskID)
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
		`SELECT status FROM job_task WHERE id = ANY($1::uuid[])`,
		uuids,
	)
	if err != nil {
		return false, err
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		count++
		var status string
		if err := rows.Scan(&status); err != nil {
			return false, err
		}
		if status != taskSucceeded {
			return false, nil
		}
	}
	return count == len(dependencyIDs), rows.Err()
}

func (s *Service) markTaskDispatchingTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID string,
	executorID string,
	requestID string,
) (bool, error) {
	tag, err := tx.Exec(
		ctx,
		`UPDATE job_task
		 SET status='DISPATCHING',
		     assigned_executor_id=$2,
		     dispatch_request_id=$3,
		     state_version=state_version+1,
		     updated_at=now()
		 WHERE id=$1::uuid AND status='PENDING'`,
		taskID,
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
	lastError string,
	lastConfirmedCommitID string,
) error {
	_, err := tx.Exec(
		ctx,
		`UPDATE loop
		 SET status=$2,
		     phase=$3,
		     last_error=NULLIF($4,''),
		     last_confirmed_commit_id=NULLIF($5,'')::uuid,
		     updated_at=now()
		 WHERE id=$1::uuid`,
		loopID,
		status,
		phase,
		strings.TrimSpace(lastError),
		strings.TrimSpace(lastConfirmedCommitID),
	)
	return err
}

func (s *Service) findJobIDByTask(ctx context.Context, tx pgx.Tx, taskID string) (string, error) {
	var jobID string
	if err := tx.QueryRow(ctx, `SELECT job_id::text FROM job_task WHERE id=$1::uuid`, taskID).Scan(&jobID); err != nil {
		if err == pgx.ErrNoRows {
			return "", nil
		}
		return "", err
	}
	return jobID, nil
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

func (s *Service) getLatestJobByLoopTx(ctx context.Context, tx pgx.Tx, loopID string) (jobRow, bool, error) {
	var row jobRow
	if err := tx.QueryRow(
		ctx,
		`SELECT id::text,round_index,COALESCE(summary_status::text,''),ended_at
		   FROM job
		  WHERE loop_id=$1::uuid
		  ORDER BY round_index DESC,created_at DESC
		  LIMIT 1`,
		loopID,
	).Scan(&row.ID, &row.RoundIndex, &row.SummaryStatus, &row.EndedAt); err != nil {
		if err == pgx.ErrNoRows {
			return jobRow{}, false, nil
		}
		return jobRow{}, false, err
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

func (s *Service) getTaskPayloadByIDTx(ctx context.Context, tx pgx.Tx, taskID string) (taskDispatchPayload, bool, error) {
	var row taskDispatchPayload
	if err := tx.QueryRow(
		ctx,
		`SELECT
		     t.id::text,
		     t.job_id::text,
		     COALESCE(t.status::text,''),
		     COALESCE(t.task_type::text,''),
		     t.round_index,
		     t.attempt,
		     COALESCE(t.depends_on::text,'[]'),
		     COALESCE(t.params::text,'{}'),
		     COALESCE(t.source_commit_id::text,''),
		     j.loop_id::text,
		     j.project_id::text,
		     COALESCE(j.plugin_id,''),
		     COALESCE(j.mode::text,''),
		     COALESCE(j.query_strategy,''),
		     COALESCE(j.params::text,'{}'),
		     COALESCE(j.resources::text,'{}'),
		     COALESCE(j.source_commit_id::text,'')
		   FROM job_task t
		   JOIN job j ON j.id=t.job_id
		  WHERE t.id=$1::uuid
		  FOR UPDATE`,
		taskID,
	).Scan(
		&row.TaskID,
		&row.JobID,
		&row.Status,
		&row.TaskType,
		&row.RoundIndex,
		&row.Attempt,
		&row.dependsOnRaw,
		&row.paramsRaw,
		&row.SourceCommitID,
		&row.LoopID,
		&row.ProjectID,
		&row.PluginID,
		&row.Mode,
		&row.QueryStrategy,
		&row.jobParamsRaw,
		&row.resourcesRaw,
		&row.jobSourceCommitID,
	); err != nil {
		if err == pgx.ErrNoRows {
			return taskDispatchPayload{}, false, nil
		}
		return taskDispatchPayload{}, false, err
	}
	if strings.TrimSpace(row.SourceCommitID) == "" {
		row.SourceCommitID = row.jobSourceCommitID
	}
	var parseErr error
	row.DependsOnTaskIDs, parseErr = parseJSONStrings(row.dependsOnRaw)
	if parseErr != nil {
		return taskDispatchPayload{}, false, parseErr
	}
	row.Params, parseErr = toStruct(row.paramsRaw)
	if parseErr != nil {
		return taskDispatchPayload{}, false, parseErr
	}
	if row.Params == nil || len(row.Params.GetFields()) == 0 {
		row.Params, parseErr = toStruct(row.jobParamsRaw)
		if parseErr != nil {
			return taskDispatchPayload{}, false, parseErr
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

func (s *Service) insertTaskEventTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID string,
	seq int64,
	ts time.Time,
	eventType string,
	payloadJSON string,
	requestID string,
) (bool, error) {
	tag, err := tx.Exec(
		ctx,
		`INSERT INTO task_event(id,task_id,seq,ts,event_type,payload,request_id,created_at,updated_at)
		 VALUES($1::uuid,$2::uuid,$3,$4,$5,$6::jsonb,NULLIF($7,''),now(),now())
		 ON CONFLICT (task_id,seq) DO NOTHING`,
		uuid.NewString(),
		taskID,
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

func (s *Service) insertMetricPointsTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID string,
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
			`INSERT INTO task_metric_point(id,task_id,step,epoch,metric_name,metric_value,ts,created_at,updated_at)
			 VALUES($1::uuid,$2::uuid,$3,$4,$5,$6,$7,now(),now())`,
			uuid.NewString(),
			taskID,
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

func (s *Service) replaceTaskCandidatesTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID string,
	candidates []*runtimecontrolv1.QueryCandidate,
) error {
	if _, err := tx.Exec(ctx, `DELETE FROM task_candidate_item WHERE task_id=$1::uuid`, taskID); err != nil {
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
			`INSERT INTO task_candidate_item(
			     id,task_id,sample_id,rank,score,reason,prediction_snapshot,created_at,updated_at
			   ) VALUES(
			     $1::uuid,$2::uuid,$3::uuid,$4,$5,$6::jsonb,'{}'::jsonb,now(),now()
			   )`,
			uuid.NewString(),
			taskID,
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

func (s *Service) mergeArtifactIntoTaskTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID string,
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
		`SELECT COALESCE(artifacts::text,'{}') FROM job_task WHERE id=$1::uuid FOR UPDATE`,
		taskID,
	).Scan(&rawArtifacts); err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("task not found: %s", taskID)
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
		`UPDATE job_task SET artifacts=$2::jsonb,updated_at=now() WHERE id=$1::uuid`,
		taskID,
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

type jobRow struct {
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

type taskDispatchPayload struct {
	TaskID           string
	JobID            string
	LoopID           string
	ProjectID        string
	SourceCommitID   string
	TaskType         string
	PluginID         string
	Mode             string
	QueryStrategy    string
	RoundIndex       int
	Attempt          int
	Status           string
	DependsOnTaskIDs []string
	Params           *structpb.Struct
	Resources        *runtimecontrolv1.ResourceSummary

	dependsOnRaw      string
	paramsRaw         string
	jobParamsRaw      string
	resourcesRaw      string
	jobSourceCommitID string
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

func decodeTaskEvent(event *runtimecontrolv1.TaskEvent) (string, map[string]any, string) {
	if event == nil {
		return "", map[string]any{}, ""
	}
	switch payload := event.GetEventPayload().(type) {
	case *runtimecontrolv1.TaskEvent_StatusEvent:
		statusText := runtimeStatusToTaskStatus(payload.StatusEvent.GetStatus())
		return "status", map[string]any{
			"status": statusText,
			"reason": strings.TrimSpace(payload.StatusEvent.GetReason()),
		}, statusText
	case *runtimecontrolv1.TaskEvent_LogEvent:
		return "log", map[string]any{
			"level":   strings.TrimSpace(payload.LogEvent.GetLevel()),
			"message": payload.LogEvent.GetMessage(),
		}, ""
	case *runtimecontrolv1.TaskEvent_ProgressEvent:
		return "progress", map[string]any{
			"epoch":       int(payload.ProgressEvent.GetEpoch()),
			"step":        int(payload.ProgressEvent.GetStep()),
			"total_steps": int(payload.ProgressEvent.GetTotalSteps()),
			"eta_sec":     int(payload.ProgressEvent.GetEtaSec()),
		}, ""
	case *runtimecontrolv1.TaskEvent_MetricEvent:
		metrics := map[string]float64{}
		for metricName, metricValue := range payload.MetricEvent.GetMetrics() {
			metrics[metricName] = metricValue
		}
		return "metric", map[string]any{
			"step":    int(payload.MetricEvent.GetStep()),
			"epoch":   int(payload.MetricEvent.GetEpoch()),
			"metrics": metrics,
		}, ""
	case *runtimecontrolv1.TaskEvent_ArtifactEvent:
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

func taskEventTime(tsMillis int64) time.Time {
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

func taskSpecsByMode(mode string) []string {
	switch mode {
	case modeSIM:
		return []string{"TRAIN", "SCORE", "SELECT", "ACTIVATE_SAMPLES", "EVAL"}
	case modeManual:
		return []string{"TRAIN", "SCORE", "UPLOAD_ARTIFACT"}
	default:
		return []string{"TRAIN", "SCORE", "SELECT", "UPLOAD_ARTIFACT"}
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
			"supported_task_types":   normalizeStringSlice(item.GetSupportedTaskTypes()),
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

func toRuntimeTaskType(raw string) runtimecontrolv1.RuntimeTaskType {
	switch strings.ToUpper(strings.TrimSpace(raw)) {
	case "TRAIN":
		return runtimecontrolv1.RuntimeTaskType_TRAIN
	case "SCORE":
		return runtimecontrolv1.RuntimeTaskType_SCORE
	case "SELECT":
		return runtimecontrolv1.RuntimeTaskType_SELECT
	case "ACTIVATE_SAMPLES":
		return runtimecontrolv1.RuntimeTaskType_ACTIVATE_SAMPLES
	case "AUTO_LABEL":
		// Backward alias.
		return runtimecontrolv1.RuntimeTaskType_ACTIVATE_SAMPLES
	case "WAIT_ANNOTATION":
		return runtimecontrolv1.RuntimeTaskType_WAIT_ANNOTATION
	case "MERGE":
		return runtimecontrolv1.RuntimeTaskType_MERGE
	case "EVAL":
		return runtimecontrolv1.RuntimeTaskType_EVAL
	case "UPLOAD_ARTIFACT":
		return runtimecontrolv1.RuntimeTaskType_UPLOAD_ARTIFACT
	default:
		return runtimecontrolv1.RuntimeTaskType_RUNTIME_TASK_TYPE_UNSPECIFIED
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

func runtimeStatusToTaskStatus(status runtimecontrolv1.RuntimeTaskStatus) string {
	switch status {
	case runtimecontrolv1.RuntimeTaskStatus_PENDING:
		return taskPending
	case runtimecontrolv1.RuntimeTaskStatus_DISPATCHING:
		return taskDispatching
	case runtimecontrolv1.RuntimeTaskStatus_RUNNING:
		return taskRunning
	case runtimecontrolv1.RuntimeTaskStatus_RETRYING:
		return taskRetrying
	case runtimecontrolv1.RuntimeTaskStatus_SUCCEEDED:
		return taskSucceeded
	case runtimecontrolv1.RuntimeTaskStatus_FAILED:
		return taskFailed
	case runtimecontrolv1.RuntimeTaskStatus_CANCELLED:
		return taskCancelled
	case runtimecontrolv1.RuntimeTaskStatus_SKIPPED:
		return taskSkipped
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

func extractJobResources(rawConfig string) map[string]any {
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(rawConfig), &payload); err != nil {
		return nil
	}
	resourcesRaw, ok := payload["job_resources_default"]
	if !ok {
		return nil
	}
	resources, ok := resourcesRaw.(map[string]any)
	if !ok {
		return nil
	}
	return resources
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
