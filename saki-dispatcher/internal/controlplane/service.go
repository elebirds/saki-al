package controlplane

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/rs/zerolog"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
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

type ControlplaneQuerier interface {
	db.Querier
	WithTx(tx pgx.Tx) *db.Queries
}

type Service struct {
	pool                    *pgxpool.Pool
	queries                 ControlplaneQuerier
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
	var (
		pool    *pgxpool.Pool
		queries ControlplaneQuerier
	)
	if repository != nil && repository.Enabled() {
		pool = repository.Pool()
		queries = db.New(pool)
	}

	return &Service{
		pool:                    pool,
		queries:                 queries,
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

func (s *Service) dbEnabled() bool {
	return s != nil && s.pool != nil && s.queries != nil
}

func (s *Service) beginTx(ctx context.Context) (pgx.Tx, error) {
	if !s.dbEnabled() {
		return nil, fmt.Errorf("database is not configured")
	}
	return s.pool.Begin(ctx)
}

func (s *Service) qtx(tx pgx.Tx) *db.Queries {
	return s.queries.WithTx(tx)
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
	if !s.dbEnabled() {
		return CommandResult{
			CommandID: commandID,
			Status:    "failed",
			Message:   "database is not configured",
			RequestID: uuid.NewString(),
		}, nil
	}

	tx, err := s.beginTx(ctx)
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
		s.persistCommandFailure(ctx, commandID, commandType, resourceID, err)
		return CommandResult{}, err
	}
	if status == "" {
		status = "applied"
	}
	if detail == "" {
		detail = status
	}

	if err := s.qtx(tx).UpdateCommandLogStatusDetail(ctx, db.UpdateCommandLogStatusDetailParams{
		CommandID: commandID,
		Status:    status,
		Detail:    detail,
	}); err != nil {
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

func (s *Service) persistCommandFailure(
	ctx context.Context,
	commandID string,
	commandType string,
	resourceID string,
	actionErr error,
) {
	if !s.dbEnabled() {
		return
	}
	tx, err := s.beginTx(ctx)
	if err != nil {
		return
	}
	defer tx.Rollback(ctx)

	requestID := uuid.NewString()
	if _, err := s.insertCommandLogTx(ctx, tx, requestID, commandID, commandType, resourceID); err != nil {
		return
	}
	detail := strings.TrimSpace(actionErr.Error())
	if detail == "" {
		detail = "command failed"
	}
	if err := s.qtx(tx).UpdateCommandLogStatusDetail(ctx, db.UpdateCommandLogStatusDetailParams{
		CommandID: commandID,
		Status:    "failed",
		Detail:    detail,
	}); err != nil {
		return
	}
	_ = tx.Commit(ctx)
}

func (s *Service) listTickLoopIDs(ctx context.Context, limit int) ([]string, error) {
	return s.queries.ListTickLoopIDs(ctx, int32(max(1, limit)))
}

func (s *Service) processLoop(ctx context.Context, loopID string) error {
	tx, err := s.beginTx(ctx)
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
		roundPGID, err := toPGUUID(latestRound.ID)
		if err != nil {
			return err
		}
		if err := s.qtx(tx).UpdateRoundWaitUser(ctx, roundPGID); err != nil {
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
	loopPGID, err := toPGUUID(loop.ID)
	if err != nil {
		return err
	}
	rows, err := s.qtx(tx).ListLoopStoppableSteps(ctx, loopPGID)
	if err != nil {
		return err
	}
	tasks := mapLoopStoppableSteps(rows)

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
	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return 0, err
	}
	next, err := s.qtx(tx).GetNextRoundIndex(ctx, loopPGID)
	if err != nil {
		return 0, err
	}
	return int(next), nil
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

	roundPGID, err := toPGUUID(roundID)
	if err != nil {
		return false, err
	}
	projectPGID, err := toPGUUID(projectID)
	if err != nil {
		return false, err
	}
	loopPGID, err := toPGUUID(loop.ID)
	if err != nil {
		return false, err
	}
	inputCommitPGID, err := toNullablePGUUID(sourceCommitID)
	if err != nil {
		return false, err
	}
	if err := s.qtx(tx).InsertRound(ctx, db.InsertRoundParams{
		RoundID:        roundPGID,
		ProjectID:      projectPGID,
		LoopID:         loopPGID,
		RoundIndex:     int32(nextRound),
		Mode:           db.Loopmode(loop.Mode),
		State:          db.Roundstatus(roundPending),
		StepCounts:     []byte(`{}`),
		PluginID:       loop.ModelArch,
		QueryStrategy:  loop.QueryStrategy,
		ResolvedParams: []byte(paramsJSON),
		Resources:      []byte(resourcesJSON),
		InputCommitID:  inputCommitPGID,
	}); err != nil {
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
		stepPGID, err := toPGUUID(stepID)
		if err != nil {
			return false, err
		}
		if err := s.qtx(tx).InsertStep(ctx, db.InsertStepParams{
			StepID:           stepPGID,
			RoundID:          roundPGID,
			StepType:         db.Steptype(stepType),
			DispatchKind:     db.Stepdispatchkind(dispatchKind),
			RoundIndex:       int32(nextRound),
			StepIndex:        int32(idx + 1),
			DependsOnStepIds: []byte(dependsOnJSON),
			ResolvedParams:   []byte(paramsJSON),
			InputCommitID:    inputCommitPGID,
		}); err != nil {
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

	if err := s.qtx(tx).UpdateLoopAfterRoundCreated(ctx, db.UpdateLoopAfterRoundCreatedParams{
		CurrentIteration: int32(nextRound),
		Phase:            db.Loopphase(phase),
		LoopID:           loopPGID,
	}); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) refreshRoundAggregateTx(ctx context.Context, tx pgx.Tx, roundID string) (string, error) {
	roundPGID, err := toPGUUID(roundID)
	if err != nil {
		return "", err
	}
	rows, err := s.qtx(tx).CountStepStatesByRound(ctx, roundPGID)
	if err != nil {
		return "", err
	}
	counts := map[string]int{}
	total := 0
	for _, row := range rows {
		state := asString(row.State)
		count := int(row.Count)
		counts[state] = count
		total += count
	}
	if total == 0 {
		return roundPending, nil
	}

	state := summarizeRoundState(counts, total)
	countsJSON, err := marshalJSON(counts)
	if err != nil {
		return "", err
	}
	if err := s.qtx(tx).UpdateRoundAggregate(ctx, db.UpdateRoundAggregateParams{
		State:      db.Roundstatus(state),
		StepCounts: []byte(countsJSON),
		RoundID:    roundPGID,
	}); err != nil {
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
	return s.queries.ListPendingStepIDs(ctx, int32(max(1, limit)))
}

func (s *Service) listReadyStepIDs(ctx context.Context, limit int) ([]string, error) {
	return s.queries.ListReadyStepIDsForUpdateSkipLocked(ctx, int32(max(1, limit)))
}

func (s *Service) dependenciesSatisfiedTx(ctx context.Context, tx pgx.Tx, dependencyIDs []string) (bool, error) {
	if len(dependencyIDs) == 0 {
		return true, nil
	}
	uuids, err := toPGUUIDs(dependencyIDs)
	if err != nil {
		return false, nil
	}
	states, err := s.qtx(tx).GetDependencyStatesByIDs(ctx, uuids)
	if err != nil {
		return false, err
	}
	for _, state := range states {
		if state != db.StepstatusSUCCEEDED {
			return false, nil
		}
	}
	return len(states) == len(dependencyIDs), nil
}

func (s *Service) markStepDispatchingTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	executorID string,
	requestID string,
) (bool, error) {
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return false, err
	}
	updated, err := s.qtx(tx).MarkStepDispatching(ctx, db.MarkStepDispatchingParams{
		AssignedExecutorID: toPGText(executorID),
		DispatchRequestID:  toPGText(requestID),
		StepID:             stepPGID,
	})
	if err != nil {
		return false, err
	}
	return updated > 0, nil
}

func (s *Service) promoteStepToReadyTx(ctx context.Context, tx pgx.Tx, stepID string) (bool, error) {
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return false, err
	}
	updated, err := s.qtx(tx).PromoteStepToReady(ctx, stepPGID)
	if err != nil {
		return false, err
	}
	return updated > 0, nil
}

func (s *Service) updateLoopStatus(ctx context.Context, tx pgx.Tx, loopID string, status string) error {
	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return err
	}
	currentStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopPGID)
	if err != nil {
		return err
	}
	target := db.Loopstatus(status)
	if !canLoopTransition(currentStatus, target) {
		return fmt.Errorf("invalid loop transition: %s -> %s", currentStatus, target)
	}
	affected, err := s.qtx(tx).UpdateLoopStatusGuarded(ctx, db.UpdateLoopStatusGuardedParams{
		Status:     target,
		LoopID:     loopPGID,
		FromStatus: currentStatus,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop transition conflict: %s -> %s", currentStatus, target)
	}
	return nil
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
	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return err
	}
	currentStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopPGID)
	if err != nil {
		return err
	}
	target := db.Loopstatus(status)
	if !canLoopTransition(currentStatus, target) {
		return fmt.Errorf("invalid loop transition: %s -> %s", currentStatus, target)
	}
	lastConfirmedCommitPGID, err := toNullablePGUUID(lastConfirmedCommitID)
	if err != nil {
		return err
	}
	affected, err := s.qtx(tx).UpdateLoopStateGuarded(ctx, db.UpdateLoopStateGuardedParams{
		Status:                target,
		Phase:                 db.Loopphase(phase),
		TerminalReason:        toNullablePGText(terminalReason),
		LastConfirmedCommitID: lastConfirmedCommitPGID,
		LoopID:                loopPGID,
		FromStatus:            currentStatus,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop state transition conflict: %s -> %s", currentStatus, target)
	}
	return nil
}

func (s *Service) findRoundIDByStep(ctx context.Context, tx pgx.Tx, stepID string) (string, error) {
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return "", nil
	}
	roundID, err := s.qtx(tx).FindRoundIDByStep(ctx, stepPGID)
	if err != nil {
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
	if !s.dbEnabled() {
		return "", "", nil
	}
	branchPGID, parseErr := toPGUUID(branchID)
	if parseErr != nil {
		return "", "", nil
	}
	row, err := s.queries.ResolveBranchHeadFromDB(ctx, branchPGID)
	if err == pgx.ErrNoRows {
		return "", "", nil
	}
	headCommitID = asString(row.HeadCommitID)
	projectID = asString(row.ProjectID)
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
	headCommitPGID, err := toPGUUID(headCommitID)
	if err != nil {
		return 0, "", err
	}
	latestCount, err := s.queries.CountCommitAnnotationsByCommit(ctx, headCommitPGID)
	if err != nil {
		return 0, "", err
	}
	var sinceCount int64
	if strings.TrimSpace(sinceCommitID) != "" {
		sinceCommitPGID, parseErr := toPGUUID(sinceCommitID)
		if parseErr != nil {
			return 0, "", parseErr
		}
		if sinceCount, err = s.queries.CountCommitAnnotationsByCommit(ctx, sinceCommitPGID); err != nil {
			return 0, "", err
		}
	}
	return max64(0, latestCount-sinceCount), headCommitID, nil
}

func (s *Service) getLatestRoundByLoopTx(ctx context.Context, tx pgx.Tx, loopID string) (roundRow, bool, error) {
	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return roundRow{}, false, err
	}
	record, err := s.qtx(tx).GetLatestRoundByLoop(ctx, loopPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return roundRow{}, false, nil
		}
		return roundRow{}, false, err
	}
	return mapLatestRound(record), true, nil
}

func (s *Service) lockLoop(ctx context.Context, tx pgx.Tx, loopID string) (loopRow, bool, error) {
	if key, ok := loopAdvisoryKey(loopID); ok {
		locked, err := s.qtx(tx).TryLoopAdvisoryXactLock(ctx, key)
		if err != nil {
			return loopRow{}, false, err
		}
		if !locked {
			return loopRow{}, false, nil
		}
	}

	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return loopRow{}, false, nil
	}
	record, err := s.qtx(tx).GetLoopForUpdate(ctx, loopPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return loopRow{}, false, nil
		}
		return loopRow{}, false, err
	}
	return mapLoopForUpdate(record), true, nil
}

func (s *Service) getStepPayloadByIDTx(ctx context.Context, tx pgx.Tx, stepID string) (stepDispatchPayload, bool, error) {
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return stepDispatchPayload{}, false, nil
	}
	record, err := s.qtx(tx).GetStepPayloadByIDForUpdate(ctx, stepPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return stepDispatchPayload{}, false, nil
		}
		return stepDispatchPayload{}, false, err
	}
	row, err := mapStepPayload(record)
	if err != nil {
		return stepDispatchPayload{}, false, err
	}
	return row, true, nil
}

func (s *Service) getCommandLogTx(ctx context.Context, tx pgx.Tx, commandID string) (commandLogEntry, bool, error) {
	record, err := s.qtx(tx).GetCommandLogByCommandID(ctx, commandID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return commandLogEntry{}, false, nil
		}
		return commandLogEntry{}, false, err
	}
	row := commandLogEntry{
		ID:     record.ID,
		Status: record.Status,
		Detail: record.Detail,
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
	requestPGID, err := toPGUUID(requestID)
	if err != nil {
		return false, err
	}
	affected, err := s.qtx(tx).InsertCommandLog(ctx, db.InsertCommandLogParams{
		RequestID:   requestPGID,
		CommandID:   commandID,
		CommandType: commandType,
		ResourceID:  resourceID,
	})
	if err != nil {
		return false, err
	}
	return affected > 0, nil
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
	eventPGID, err := toPGUUID(uuid.NewString())
	if err != nil {
		return false, err
	}
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return false, err
	}
	affected, err := s.qtx(tx).InsertStepEvent(ctx, db.InsertStepEventParams{
		EventID:   eventPGID,
		StepID:    stepPGID,
		Seq:       int32(seq),
		Ts:        toPGTimestamp(ts),
		EventType: eventType,
		Payload:   []byte(payloadJSON),
		RequestID: toNullablePGText(requestID),
	})
	if err != nil {
		return false, err
	}
	return affected > 0, nil
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
	if err := s.qtx(tx).UpdateCommandLogStatusDetail(ctx, db.UpdateCommandLogStatusDetailParams{
		CommandID: commandID,
		Status:    "applied",
		Detail:    detail,
	}); err != nil {
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
	pgIDs, err := toPGUUIDs(stepIDs)
	if err != nil {
		return err
	}
	return s.qtx(tx).CancelStepsByIDs(ctx, db.CancelStepsByIDsParams{
		LastError: toPGText(reason),
		StepIds:   pgIDs,
	})
}

func (s *Service) loopHasActiveStepsTx(ctx context.Context, tx pgx.Tx, loopID string) (bool, error) {
	loopPGID, err := toPGUUID(loopID)
	if err != nil {
		return false, err
	}
	count, err := s.qtx(tx).CountLoopActiveSteps(ctx, loopPGID)
	if err != nil {
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
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return err
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyStepMetricPointsParams, 0, len(metrics))
	for metricName, metricValue := range metrics {
		cleanMetricName := strings.TrimSpace(metricName)
		if cleanMetricName == "" {
			continue
		}
		metricPGID, err := toPGUUID(uuid.NewString())
		if err != nil {
			return err
		}
		rows = append(rows, db.CopyStepMetricPointsParams{
			ID:          metricPGID,
			StepID:      stepPGID,
			Step:        int32(step),
			Epoch:       toPGInt4(epoch),
			MetricName:  cleanMetricName,
			MetricValue: metricValue,
			Ts:          toPGTimestamp(ts),
			CreatedAt:   now,
			UpdatedAt:   now,
		})
	}
	if len(rows) == 0 {
		return nil
	}
	if _, err := s.qtx(tx).CopyStepMetricPoints(ctx, rows); err != nil {
		return err
	}
	return nil
}

func (s *Service) replaceStepCandidatesTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID string,
	candidates []*runtimecontrolv1.QueryCandidate,
) error {
	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return err
	}
	if err := s.qtx(tx).DeleteStepCandidatesByStepID(ctx, stepPGID); err != nil {
		return err
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyStepCandidateItemsParams, 0, len(candidates))
	for idx, item := range candidates {
		sampleIDText := strings.TrimSpace(item.GetSampleId())
		if sampleIDText == "" {
			continue
		}
		parsedSampleID, err := toPGUUID(sampleIDText)
		if err != nil {
			continue
		}
		reasonJSON, err := marshalJSON(structToMap(item.GetReason()))
		if err != nil {
			return err
		}
		candidatePGID, err := toPGUUID(uuid.NewString())
		if err != nil {
			return err
		}
		rows = append(rows, db.CopyStepCandidateItemsParams{
			ID:                 candidatePGID,
			StepID:             stepPGID,
			SampleID:           parsedSampleID,
			Rank:               int32(idx + 1),
			Score:              item.GetScore(),
			Reason:             []byte(reasonJSON),
			PredictionSnapshot: []byte(`{}`),
			CreatedAt:          now,
			UpdatedAt:          now,
		})
	}
	if len(rows) > 0 {
		if _, err := s.qtx(tx).CopyStepCandidateItems(ctx, rows); err != nil {
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

	stepPGID, err := toPGUUID(stepID)
	if err != nil {
		return fmt.Errorf("step not found: %s", stepID)
	}
	rawArtifactsAny, err := s.qtx(tx).GetStepArtifactsForUpdate(ctx, stepPGID)
	rawArtifacts := asString(rawArtifactsAny)
	if err != nil {
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
	return s.qtx(tx).UpdateStepArtifacts(ctx, db.UpdateStepArtifactsParams{
		Artifacts: []byte(artifactsJSON),
		StepID:    stepPGID,
	})
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
	var result []string
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
