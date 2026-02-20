package controlplane

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) StartLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, "start_loop", loopID, func(tx pgx.Tx, commandID string) (string, string, error) {
		loopUUID, err := parseUUID(loopID)
		if err != nil {
			return "rejected", "loop not found", nil
		}
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
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
		loopUUID, err := parseUUID(loopID)
		if err != nil {
			return "rejected", "loop not found", nil
		}
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
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
		loopUUID, err := parseUUID(loopID)
		if err != nil {
			return "rejected", "loop not found", nil
		}
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
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
		loopUUID, err := parseUUID(loopID)
		if err != nil {
			return "rejected", "loop not found", nil
		}
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
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
		loopUUID, err := parseUUID(loopID)
		if err != nil {
			return "rejected", "loop not found", nil
		}
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
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
			if latestCommitID != nil {
				if err := s.qtx(tx).UpdateLoopLastConfirmedCommit(ctx, db.UpdateLoopLastConfirmedCommitParams{
					LastConfirmedCommitID: *latestCommitID,
					LoopID:                loop.ID,
				}); err != nil {
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
		roundPGID, err := parseUUID(roundID)
		if err != nil {
			return "rejected", "round not found", nil
		}
		currentStatusRaw, err := s.qtx(tx).GetRoundState(ctx, roundPGID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return "rejected", "round not found", nil
			}
			return "", "", err
		}
		currentStatus := currentStatusRaw
		if _, ok := terminalRoundStatuses[currentStatus]; ok {
			return "applied", "round already in terminal state", nil
		}

		affected, err := s.qtx(tx).UpdateRoundStateWithReasonGuarded(ctx, db.UpdateRoundStateWithReasonGuardedParams{
			State:          roundCancelled,
			TerminalReason: toPGText(reason),
			RoundID:        roundPGID,
			FromState:      currentStatus,
		})
		if err != nil {
			return "", "", err
		}
		if affected == 0 {
			return "conflict", "round state changed concurrently", nil
		}
		stepIDs, err := s.qtx(tx).ListRoundActiveStepIDs(ctx, roundPGID)
		if err != nil {
			return "", "", err
		}
		if err := s.qtx(tx).CancelStepsByRound(ctx, db.CancelStepsByRoundParams{
			LastError: toPGText(reason),
			RoundID:   roundPGID,
		}); err != nil {
			return "", "", err
		}
		for _, stepID := range stepIDs {
			s.dispatcher.StopStep(stepID.String(), reason)
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
		stepPGID, err := parseUUID(stepID)
		if err != nil {
			return "rejected", "step not found", nil
		}
		currentStatusRaw, err := s.qtx(tx).GetStepState(ctx, stepPGID)
		currentStatus := currentStatusRaw
		if err != nil {
			if err == pgx.ErrNoRows {
				return "rejected", "step not found", nil
			}
			return "", "", err
		}
		if currentStatus == stepSucceeded || currentStatus == stepFailed || currentStatus == stepCancelled || currentStatus == stepSkipped {
			return "applied", "step already in terminal state", nil
		}

		if err := s.qtx(tx).CancelStepByID(ctx, db.CancelStepByIDParams{
			LastError: toPGText(reason),
			StepID:    stepPGID,
		}); err != nil {
			return "", "", err
		}
		s.dispatcher.StopStep(stepPGID.String(), reason)
		return "applied", "stop_step applied", nil
	})
}

func (s *Service) TriggerDispatch(ctx context.Context, commandID string, stepID string) (CommandResult, error) {
	stepID = strings.TrimSpace(stepID)
	return s.withCommand(ctx, commandID, "trigger_dispatch", stepID, func(tx pgx.Tx, _ string) (string, string, error) {
		if stepID != "" {
			stepUUID, err := parseUUID(stepID)
			if err != nil {
				return "rejected", "step not found", nil
			}
			dispatched, err := s.dispatchStepByID(ctx, stepUUID)
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

func (s *Service) listTickLoopIDs(ctx context.Context, limit int) ([]uuid.UUID, error) {
	return s.queries.ListTickLoopIDs(ctx, int32(max(1, limit)))
}

func (s *Service) processLoop(ctx context.Context, loopID uuid.UUID) error {
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
		if err := s.qtx(tx).UpdateRoundWaitUser(ctx, latestRound.ID); err != nil {
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
	rows, err := s.qtx(tx).ListLoopStoppableSteps(ctx, loop.ID)
	if err != nil {
		return err
	}
	tasks := mapLoopStoppableSteps(rows)

	if len(tasks) > 0 {
		reason := "loop stopping requested"
		immediateCancelStepIDs := make([]uuid.UUID, 0, len(tasks))
		forceCancelStepIDs := make([]uuid.UUID, 0, len(tasks))
		hasInflightRunning := false
		now := time.Now().UTC()

		for _, item := range tasks {
			switch item.State {
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
					Str("loop_id", loop.ID.String()).
					Str("step_id", stepID.String()).
					Dur("force_after", s.stopForceCancelAfter).
					Msg("STOPPING 超时后强制取消步骤")
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

func (s *Service) Tick(ctx context.Context) error {
	if !s.dbEnabled() {
		return nil
	}
	s.maybeCleanupPredictionRows(ctx)
	loopIDs, err := s.listTickLoopIDs(ctx, 512)
	if err != nil {
		return err
	}
	for _, loopID := range loopIDs {
		if err := s.processLoop(ctx, loopID); err != nil {
			s.logger.Warn().Str("loop_id", loopID.String()).Err(err).Msg("处理 loop 失败")
		}
	}
	_, err = s.dispatchPending(ctx, 256)
	return err
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

func (s *Service) getNextRoundIndexTx(ctx context.Context, tx pgx.Tx, loopID uuid.UUID) (int, error) {
	next, err := s.qtx(tx).GetNextRoundIndex(ctx, loopID)
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
		s.logger.Warn().Err(err).Str("loop_id", loop.ID.String()).Msg("解析分支头失败，继续使用空 source commit")
	}
	projectID := loop.ProjectID
	if projectIDFromBranch != nil {
		projectID = *projectIDFromBranch
	}

	roundID := uuid.New()
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

	if err := s.qtx(tx).InsertRound(ctx, db.InsertRoundParams{
		RoundID:        roundID,
		ProjectID:      projectID,
		LoopID:         loop.ID,
		RoundIndex:     int32(nextRound),
		Mode:           loop.Mode,
		State:          roundPending,
		StepCounts:     []byte(`{}`),
		PluginID:       loop.ModelArch,
		QueryStrategy:  loop.QueryStrategy,
		ResolvedParams: []byte(paramsJSON),
		Resources:      []byte(resourcesJSON),
		InputCommitID:  sourceCommitID,
	}); err != nil {
		return false, err
	}

	stepSpecs := stepSpecsByMode(loop.Mode)
	if len(stepSpecs) == 0 {
		return false, fmt.Errorf("unsupported loop mode for step specs: %s", loop.Mode)
	}
	var previousStepID *uuid.UUID
	for idx, stepType := range stepSpecs {
		stepID := uuid.New()
		dependsOn := make([]uuid.UUID, 0, 1)
		if previousStepID != nil {
			dependsOn = append(dependsOn, *previousStepID)
		}
		dependsOnJSON, err := marshalJSON(dependsOn)
		if err != nil {
			return false, err
		}
		dispatchKind := db.StepdispatchkindDISPATCHABLE
		if isOrchestratorStepType(stepType) {
			dispatchKind = db.StepdispatchkindORCHESTRATOR
		}
		if err := s.qtx(tx).InsertStep(ctx, db.InsertStepParams{
			StepID:           stepID,
			RoundID:          roundID,
			StepType:         stepType,
			DispatchKind:     dispatchKind,
			RoundIndex:       int32(nextRound),
			StepIndex:        int32(idx + 1),
			DependsOnStepIds: []byte(dependsOnJSON),
			ResolvedParams:   []byte(paramsJSON),
			InputCommitID:    sourceCommitID,
		}); err != nil {
			return false, err
		}
		previousStepID = &stepID
		if idx == 0 {
			s.dispatcher.QueueStep(stepID.String())
		}
	}

	phase, ok := phaseForStep(loop.Mode, stepSpecs[0])
	if !ok {
		return false, fmt.Errorf("cannot resolve initial phase for loop mode=%s step_type=%s", loop.Mode, stepSpecs[0])
	}

	if err := s.qtx(tx).UpdateLoopAfterRoundCreated(ctx, db.UpdateLoopAfterRoundCreatedParams{
		CurrentIteration: int32(nextRound),
		Phase:            phase,
		LoopID:           loop.ID,
	}); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) refreshRoundAggregateTx(ctx context.Context, tx pgx.Tx, roundID uuid.UUID) (db.Roundstatus, error) {
	rows, err := s.qtx(tx).CountStepStatesByRound(ctx, roundID)
	if err != nil {
		return "", err
	}
	counts := map[db.Stepstatus]int{}
	total := 0
	for _, row := range rows {
		state := row.State
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
		State:      state,
		StepCounts: []byte(countsJSON),
		RoundID:    roundID,
	}); err != nil {
		return "", err
	}
	return state, nil
}

func summarizeRoundState(counts map[db.Stepstatus]int, total int) db.Roundstatus {
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

func (s *Service) updateLoopStatus(ctx context.Context, tx pgx.Tx, loopID uuid.UUID, status db.Loopstatus) error {
	currentStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopID)
	if err != nil {
		return err
	}
	target := status
	if !canLoopTransition(currentStatus, target) {
		return fmt.Errorf("非法 loop 状态迁移: %s -> %s", currentStatus, target)
	}
	affected, err := s.qtx(tx).UpdateLoopStatusGuarded(ctx, db.UpdateLoopStatusGuardedParams{
		Status:     target,
		LoopID:     loopID,
		FromStatus: currentStatus,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop 状态迁移冲突: %s -> %s", currentStatus, target)
	}
	return nil
}

func (s *Service) updateLoopState(
	ctx context.Context,
	tx pgx.Tx,
	loopID uuid.UUID,
	status db.Loopstatus,
	phase db.Loopphase,
	terminalReason string,
	lastConfirmedCommitID *uuid.UUID,
) error {
	currentStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopID)
	if err != nil {
		return err
	}
	target := status
	if !canLoopTransition(currentStatus, target) {
		return fmt.Errorf("非法 loop 状态迁移: %s -> %s", currentStatus, target)
	}
	affected, err := s.qtx(tx).UpdateLoopStateGuarded(ctx, db.UpdateLoopStateGuardedParams{
		Status:                target,
		Phase:                 phase,
		TerminalReason:        toNullablePGText(terminalReason),
		LastConfirmedCommitID: lastConfirmedCommitID,
		LoopID:                loopID,
		FromStatus:            currentStatus,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop 状态写入冲突: %s -> %s", currentStatus, target)
	}
	return nil
}

func (s *Service) getLatestRoundByLoopTx(ctx context.Context, tx pgx.Tx, loopID uuid.UUID) (roundRow, bool, error) {
	record, err := s.qtx(tx).GetLatestRoundByLoop(ctx, loopID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return roundRow{}, false, nil
		}
		return roundRow{}, false, err
	}
	return mapLatestRound(record), true, nil
}

func (s *Service) lockLoop(ctx context.Context, tx pgx.Tx, loopID uuid.UUID) (loopRow, bool, error) {
	if key, ok := loopAdvisoryKey(loopID); ok {
		locked, err := s.qtx(tx).TryLoopAdvisoryXactLock(ctx, key)
		if err != nil {
			return loopRow{}, false, err
		}
		if !locked {
			return loopRow{}, false, nil
		}
	}

	record, err := s.qtx(tx).GetLoopForUpdate(ctx, loopID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return loopRow{}, false, nil
		}
		return loopRow{}, false, err
	}
	return mapLoopForUpdate(record), true, nil
}

func (s *Service) resolveBranchHead(ctx context.Context, branchID uuid.UUID) (headCommitID *uuid.UUID, projectID *uuid.UUID, err error) {
	if s.domainClient != nil && s.domainClient.Enabled() {
		response, callErr := s.domainClient.GetBranchHead(ctx, branchID.String())
		if callErr == nil && response.GetFound() {
			headValue := strings.TrimSpace(response.GetHeadCommitId())
			projectValue := strings.TrimSpace(response.GetProjectId())
			if headValue == "" || projectValue == "" {
				return nil, nil, nil
			}
			parsedHead, parseErr := parseUUID(headValue)
			if parseErr != nil {
				return nil, nil, parseErr
			}
			parsedProject, parseErr := parseUUID(projectValue)
			if parseErr != nil {
				return nil, nil, parseErr
			}
			return &parsedHead, &parsedProject, nil
		}
	}
	if !s.dbEnabled() {
		return nil, nil, nil
	}
	row, err := s.queries.ResolveBranchHeadFromDB(ctx, branchID)
	if err == pgx.ErrNoRows {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	return &row.HeadCommitID, &row.ProjectID, nil
}

func (s *Service) countNewLabels(
	ctx context.Context,
	projectID uuid.UUID,
	branchID uuid.UUID,
	sinceCommitID *uuid.UUID,
) (newLabels int64, latestCommitID *uuid.UUID, err error) {
	if s.domainClient != nil && s.domainClient.Enabled() {
		sinceCommit := ""
		if sinceCommitID != nil {
			sinceCommit = sinceCommitID.String()
		}
		response, callErr := s.domainClient.CountNewLabelsSinceCommit(ctx, projectID.String(), branchID.String(), sinceCommit)
		if callErr == nil {
			latestCommit := strings.TrimSpace(response.GetLatestCommitId())
			if latestCommit == "" {
				return response.GetNewLabelCount(), nil, nil
			}
			parsedLatest, parseErr := parseUUID(latestCommit)
			if parseErr != nil {
				return 0, nil, parseErr
			}
			return response.GetNewLabelCount(), &parsedLatest, nil
		}
	}
	headCommitID, _, err := s.resolveBranchHead(ctx, branchID)
	if err != nil || headCommitID == nil {
		return 0, nil, err
	}
	latestCount, err := s.queries.CountCommitAnnotationsByCommit(ctx, *headCommitID)
	if err != nil {
		return 0, nil, err
	}
	var sinceCount int64
	if sinceCommitID != nil {
		if sinceCount, err = s.queries.CountCommitAnnotationsByCommit(ctx, *sinceCommitID); err != nil {
			return 0, nil, err
		}
	}
	return max64(0, latestCount-sinceCount), headCommitID, nil
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
		s.logger.Warn().Err(err).Time("cutoff", cutoff).Msg("清理预测数据失败")
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
		Msg("预测数据清理完成")
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
