package controlplane

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/grpc/codes"
	grpcstatus "google.golang.org/grpc/status"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

type alConfirmRevealProbe struct {
	roundID               uuid.UUID
	branchID              uuid.UUID
	configuredMinRequired int
	revealedCount         int
	selectedCount         int
	effectiveMinRequired  int
	latestCommitID        *uuid.UUID
}

func (s *Service) StartLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, commandID string) (string, string, error) {
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
		if loop.Lifecycle != lifecycleDraft {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot be started", loop.Lifecycle), nil
		}
		if err := s.updateLoopLifecycle(ctx, tx, loop.ID, lifecycleRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasRound(ctx, tx, loop, commandID); err != nil {
			return "", "", err
		}
		return "applied", "start_loop applied", nil
	})
}

func (s *Service) StartNextRound(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, commandID string) (string, string, error) {
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
		var expectedPhase db.Loopphase
		switch loop.Mode {
		case modeAL:
			expectedPhase = phaseALWaitAnnotation
		case modeManual:
			expectedPhase = phaseManualEval
		default:
			return "rejected", "start_next_round only supports active-learning/manual loop", nil
		}
		if loop.Phase != expectedPhase {
			if loop.Mode == modeAL {
				return "rejected", "loop is not in al_wait_user phase", nil
			}
			return "rejected", "loop is not in manual_eval phase", nil
		}
		if loop.Lifecycle != lifecycleRunning {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot start next round", loop.Lifecycle), nil
		}

		latestRound, found, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
		if err != nil {
			return "", "", err
		}
		if !found {
			return "rejected", "no latest round found", nil
		}
		if latestRound.SummaryStatus != roundCompleted {
			return "rejected", fmt.Sprintf("latest round is not completed: %s", latestRound.SummaryStatus), nil
		}
		if loop.Mode == modeAL && latestRound.ConfirmedAt == nil {
			return "rejected", "latest round is not confirmed", nil
		}

		inFlightCount, err := s.qtx(tx).CountLoopInFlightSteps(ctx, loop.ID)
		if err != nil {
			return "", "", err
		}
		if inFlightCount > 0 {
			return "rejected", fmt.Sprintf("loop has %d in-flight steps", inFlightCount), nil
		}

		nextRound, err := s.getNextRoundIndexTx(ctx, tx, loop.ID)
		if err != nil {
			return "", "", err
		}
		if nextRound > loop.MaxRounds {
			finalizePhase := phaseALFinalize
			completedMsg := "active-learning loop completed"
			if loop.Mode == modeManual {
				finalizePhase = phaseManualFinalize
				completedMsg = "manual loop completed"
			}
			if err := s.updateLoopRuntime(
				ctx,
				tx,
				loop.ID,
				lifecycleCompleted,
				finalizePhase,
				terminalReasonSuccess,
				loop.LastConfirmedCommitID,
			); err != nil {
				return "", "", err
			}
			return "applied", completedMsg, nil
		}

		created, err := s.createNextRoundTx(ctx, tx, loop, commandID)
		if err != nil {
			return "", "", err
		}
		if !created {
			return "rejected", "cannot create next round", nil
		}
		return "applied", "start_next_round applied", nil
	})
}

func (s *Service) PauseLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
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
		if loop.Lifecycle != lifecycleRunning {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot be paused", loop.Lifecycle), nil
		}
		if err := s.updateLoopLifecycle(ctx, tx, loop.ID, lifecyclePaused); err != nil {
			return "", "", err
		}
		return "applied", "pause_loop applied", nil
	})
}

func (s *Service) ResumeLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, commandID string) (string, string, error) {
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
		if loop.Lifecycle != lifecyclePaused {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot be resumed", loop.Lifecycle), nil
		}
		if err := s.updateLoopLifecycle(ctx, tx, loop.ID, lifecycleRunning); err != nil {
			return "", "", err
		}
		if _, err := s.ensureLoopHasRound(ctx, tx, loop, commandID); err != nil {
			return "", "", err
		}
		return "applied", "resume_loop applied", nil
	})
}

func (s *Service) StopLoop(ctx context.Context, commandID string, loopID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
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
		if loop.Lifecycle != lifecycleRunning && loop.Lifecycle != lifecyclePaused {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot be stopped", loop.Lifecycle), nil
		}
		if err := s.updateLoopLifecycle(ctx, tx, loop.ID, lifecycleStopping); err != nil {
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
	loopUUID, parseErr := parseUUID(loopID)
	var (
		preflightProbe      *alConfirmRevealProbe
		preflightRejectHint string
	)
	if parseErr == nil && s.domainClient != nil && s.domainClient.Enabled() {
		preflightCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		probe, err := s.preflightALConfirmReveal(preflightCtx, loopUUID, force)
		if err != nil {
			if st, ok := grpcstatus.FromError(err); ok && st.Code() == codes.InvalidArgument {
				preflightRejectHint = st.Message()
			} else {
				s.logger.Warn().Err(err).Str("loop_id", loopID).Msg("confirm 预探测失败，回退事务内判定")
			}
		} else {
			preflightProbe = probe
		}
	}

	return s.withCommand(ctx, commandID, func(tx pgx.Tx, commandID string) (string, string, error) {
		if parseErr != nil {
			return "rejected", "loop not found", nil
		}
		if preflightRejectHint != "" {
			return "rejected", preflightRejectHint, nil
		}
		var err error
		loop, ok, err := s.lockLoop(ctx, tx, loopUUID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "rejected", "loop not found", nil
		}

		switch loop.Mode {
		case modeManual:
			return "rejected", "manual mode does not require confirm", nil

		case modeAL:
			if loop.Phase != phaseALWaitAnnotation {
				return "rejected", "active-learning loop is not waiting for annotation", nil
			}
			latestRound, found, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
			if err != nil {
				return "", "", err
			}
			if !found {
				return "rejected", "no round found for active-learning confirm", nil
			}
			if latestRound.SummaryStatus != roundCompleted {
				return "rejected", fmt.Sprintf("latest round is not completed: %s", latestRound.SummaryStatus), nil
			}
			if latestRound.ConfirmedAt != nil {
				return "rejected", "latest round already confirmed", nil
			}

			latestCommitID := loop.LastConfirmedCommitID
			minRequired := loop.MinNewLabelsPerRound
			if minRequired <= 0 {
				minRequired = 1
			}
			revealedCount := 0
			selectedCount := 0
			effectiveMinRequired := minRequired
			if s.domainClient != nil && s.domainClient.Enabled() {
				usedPreflight := false
				if preflightProbe != nil &&
					preflightProbe.roundID == latestRound.ID &&
					preflightProbe.branchID == loop.BranchID &&
					preflightProbe.configuredMinRequired == minRequired {
					usedPreflight = true
					revealedCount = preflightProbe.revealedCount
					selectedCount = preflightProbe.selectedCount
					effectiveMinRequired = preflightProbe.effectiveMinRequired
					if effectiveMinRequired < 0 {
						effectiveMinRequired = 0
					}
					latestCommitID = preflightProbe.latestCommitID
					if !force && revealedCount < effectiveMinRequired {
						return "rejected", fmt.Sprintf(
							"revealed samples %d < min_required %d (configured=%d, selected=%d)",
							revealedCount,
							effectiveMinRequired,
							minRequired,
							preflightProbe.selectedCount,
						), nil
					}
				}

				if !usedPreflight {
					response, err := s.domainClient.ResolveRoundReveal(
						ctx,
						loop.ID.String(),
						latestRound.ID.String(),
						loop.BranchID.String(),
						force,
						int32(minRequired),
					)
					if err != nil {
						if st, ok := grpcstatus.FromError(err); ok && st.Code() == codes.InvalidArgument {
							return "rejected", st.Message(), nil
						}
						return "", "", err
					}
					revealedCount = int(response.GetRevealedCount())
					selectedCount = int(response.GetSelectedCount())
					effectiveMinRequired = int(response.GetEffectiveMinRequired())
					if effectiveMinRequired < 0 {
						effectiveMinRequired = 0
					}
					if !force && revealedCount < effectiveMinRequired {
						return "rejected", fmt.Sprintf(
							"revealed samples %d < min_required %d (configured=%d, selected=%d)",
							revealedCount,
							effectiveMinRequired,
							minRequired,
							selectedCount,
						), nil
					}
					latestCommitRaw := strings.TrimSpace(response.GetLatestCommitId())
					if latestCommitRaw != "" {
						parsedCommitID, parseErr := parseUUID(latestCommitRaw)
						if parseErr != nil {
							return "", "", parseErr
						}
						latestCommitID = &parsedCommitID
					}
				}
			} else {
				if !force {
					newLabels, latestCommit, err := s.countNewLabels(ctx, loop.ProjectID, loop.BranchID, loop.LastConfirmedCommitID)
					if err != nil {
						return "", "", err
					}
					if int(newLabels) < minRequired {
						return "rejected", fmt.Sprintf("new labels %d < min_required %d", newLabels, minRequired), nil
					}
					latestCommitID = latestCommit
					revealedCount = int(newLabels)
				} else {
					headCommitID, _, err := s.resolveBranchHead(ctx, loop.BranchID)
					if err == nil {
						latestCommitID = headCommitID
					}
				}
			}

			confirmedRows, err := s.qtx(tx).MarkRoundConfirmed(ctx, db.MarkRoundConfirmedParams{
				ConfirmedRevealedCount:        int32(revealedCount),
				ConfirmedSelectedCount:        int32(selectedCount),
				ConfirmedEffectiveMinRequired: int32(effectiveMinRequired),
				RoundID:                       latestRound.ID,
			})
			if err != nil {
				return "", "", err
			}
			if confirmedRows == 0 {
				return "rejected", "latest round is already confirmed or not completed", nil
			}
			if latestCommitID != nil {
				if err := s.qtx(tx).UpdateLoopLastConfirmedCommit(ctx, db.UpdateLoopLastConfirmedCommitParams{
					LastConfirmedCommitID: *latestCommitID,
					LoopID:                loop.ID,
				}); err != nil {
					return "", "", err
				}
			}
			return "applied", fmt.Sprintf("active-learning confirm accepted (revealed=%d)", revealedCount), nil

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
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
		roundPGID, err := parseUUID(roundID)
		if err != nil {
			return "rejected", "round not found", nil
		}
		currentLifecycleRaw, err := s.qtx(tx).GetRoundState(ctx, roundPGID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return "rejected", "round not found", nil
			}
			return "", "", err
		}
		currentLifecycle := currentLifecycleRaw
		if _, ok := terminalRoundStatuses[currentLifecycle]; ok {
			return "applied", "round already in terminal state", nil
		}

		affected, err := s.qtx(tx).UpdateRoundStateWithReasonGuarded(ctx, db.UpdateRoundStateWithReasonGuardedParams{
			State:          roundCancelled,
			TerminalReason: toPGText(reason),
			RoundID:        roundPGID,
			FromState:      currentLifecycle,
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
			taskID, mapped, mapErr := s.resolveTaskIDForStepTx(ctx, tx, stepID)
			if mapErr != nil {
				return "", "", mapErr
			}
			if !mapped {
				continue
			}
			s.dispatcher.StopTask(taskID.String(), reason)
		}
		return "applied", "stop_round applied", nil
	})
}

func (s *Service) RetryRound(
	ctx context.Context,
	commandID string,
	roundID string,
	reason string,
) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested retry"
	}
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
		roundPGID, err := parseUUID(roundID)
		if err != nil {
			return "rejected", "round not found", nil
		}

		targetRound, err := s.qtx(tx).GetRoundForRetry(ctx, roundPGID)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return "rejected", "round not found", nil
			}
			return "", "", err
		}
		if targetRound.State != roundFailed {
			return "rejected", fmt.Sprintf("round in state %s cannot retry", targetRound.State), nil
		}

		loop, ok, err := s.lockLoop(ctx, tx, targetRound.LoopID)
		if err != nil {
			return "", "", err
		}
		if !ok {
			return "conflict", "loop is busy, please retry", nil
		}
		if loop.Lifecycle != lifecycleFailed {
			return "rejected", fmt.Sprintf("loop in lifecycle %s cannot retry round", loop.Lifecycle), nil
		}

		latestRound, found, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
		if err != nil {
			return "", "", err
		}
		if !found || latestRound.ID != targetRound.ID {
			return "rejected", "only latest failed round can be retried", nil
		}
		if latestRound.SummaryStatus != roundFailed {
			return "rejected", "latest round is not failed", nil
		}

		// BUGFIX(2026-02-27): retry guard should only check in-flight steps.
		// Failed rounds keep downstream steps in PENDING; treating them as active blocks all retries.
		activeSteps, err := s.qtx(tx).CountLoopInFlightSteps(ctx, loop.ID)
		if err != nil {
			return "", "", err
		}
		if int(activeSteps) > 0 {
			return "rejected", "loop still has active steps", nil
		}

		// Retry should reactivate the loop, otherwise newly created attempt
		// remains undispatchable because dispatch queries only scan RUNNING loops.
		if err := s.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleRunning,
			loop.Phase,
			"",
			loop.LastConfirmedCommitID,
		); err != nil {
			return "", "", err
		}

		nextAttempt, err := s.getNextRoundAttemptIndexTx(ctx, tx, loop.ID, int(targetRound.RoundIndex))
		if err != nil {
			return "", "", err
		}
		createdRoundID, err := s.createRoundAttemptTx(
			ctx,
			tx,
			loop,
			int(targetRound.RoundIndex),
			nextAttempt,
			&targetRound.ID,
			reason,
		)
		if err != nil {
			return "", "", err
		}
		if createdRoundID == nil {
			return "rejected", "failed to create retry attempt", nil
		}
		return "applied", createdRoundID.String(), nil
	})
}

func (s *Service) StopTask(ctx context.Context, commandID string, taskID string, reason string) (CommandResult, error) {
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "user requested stop"
	}
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
		taskPGID, err := parseUUID(taskID)
		if err != nil {
			return "rejected", "task not found", nil
		}
		stepPGID, found, err := s.resolveStepIDForTaskTx(ctx, tx, taskPGID)
		if err != nil {
			return "", "", err
		}
		if !found {
			taskRow, taskFound, taskErr := s.getTaskForUpdateTx(ctx, tx, taskPGID)
			if taskErr != nil {
				return "", "", taskErr
			}
			if !taskFound {
				return "rejected", "task not found", nil
			}
			if isTerminalTaskStatus(taskRow.Status) {
				return "applied", "task already in terminal state", nil
			}
			_, updateErr := tx.Exec(
				ctx,
				`UPDATE task
				 SET status = 'CANCELLED'::taskstatus,
				     last_error = $2::text,
				     ended_at = COALESCE(ended_at, now()),
				     updated_at = now()
				 WHERE id = $1`,
				taskPGID,
				reason,
			)
			if updateErr != nil {
				return "", "", updateErr
			}
			s.dispatcher.StopTask(taskPGID.String(), reason)
			return "applied", "stop_task applied", nil
		}
		currentState, err := s.qtx(tx).GetStepState(ctx, stepPGID)
		if err != nil {
			if err == pgx.ErrNoRows {
				return "rejected", "task not found", nil
			}
			return "", "", err
		}
		if currentState == stepSucceeded || currentState == stepFailed || currentState == stepCancelled || currentState == stepSkipped {
			return "applied", "task already in terminal state", nil
		}
		if err := s.qtx(tx).CancelStepByID(ctx, db.CancelStepByIDParams{
			LastError: toPGText(reason),
			StepID:    stepPGID,
		}); err != nil {
			return "", "", err
		}
		s.dispatcher.StopTask(taskPGID.String(), reason)
		return "applied", "stop_task applied", nil
	})
}

func (s *Service) DispatchTask(ctx context.Context, commandID string, taskID string) (CommandResult, error) {
	return s.withCommand(ctx, commandID, func(tx pgx.Tx, _ string) (string, string, error) {
		taskPGID, err := parseUUID(taskID)
		if err != nil {
			return "rejected", "task not found", nil
		}
		stepPGID, found, err := s.resolveStepIDForTaskTx(ctx, tx, taskPGID)
		if err != nil {
			return "", "", err
		}
		if !found {
			taskRow, taskFound, taskErr := s.getTaskForUpdateTx(ctx, tx, taskPGID)
			if taskErr != nil {
				return "", "", taskErr
			}
			if !taskFound {
				return "rejected", "task not found", nil
			}
			if isTerminalTaskStatus(taskRow.Status) {
				return "rejected", "task is in terminal state", nil
			}
			if normalizeTaskEnumText(taskRow.Kind) != "PREDICTION" {
				return "rejected", "task is not dispatchable", nil
			}
			switch normalizeTaskEnumText(taskRow.Status) {
			case "PENDING", "READY", "RETRYING":
			default:
				return "rejected", "task is not dispatchable", nil
			}
			s.dispatcher.QueueTask(taskPGID.String())
			return "applied", "dispatch_task queued", nil
		}
		currentState, err := s.qtx(tx).GetStepState(ctx, stepPGID)
		if err != nil {
			if err == pgx.ErrNoRows {
				return "rejected", "task not found", nil
			}
			return "", "", err
		}
		if currentState == stepSucceeded || currentState == stepFailed || currentState == stepCancelled || currentState == stepSkipped {
			return "rejected", "task is in terminal state", nil
		}
		s.dispatcher.QueueTask(taskPGID.String())
		return "applied", "dispatch_task queued", nil
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

	switch loop.Lifecycle {
	case lifecycleStopping:
		return s.processStoppingLoopTx(ctx, tx, loop)
	case lifecycleRunning:
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
	roundStatus, err = s.normalizeRunningRoundStatusTx(ctx, tx, loop, latestRound, roundStatus)
	if err != nil {
		return err
	}
	if _, ok := terminalRoundStatuses[roundStatus]; !ok {
		return s.handleNonTerminalRoundByModeTx(ctx, tx, loop, roundStatus)
	}

	if roundStatus == roundFailed || roundStatus == roundCancelled {
		return s.markLoopFailedByRoundTx(ctx, tx, loop)
	}

	return s.handleTerminalRoundByModeTx(ctx, tx, loop, latestRound)
}

func (s *Service) normalizeRunningRoundStatusTx(
	ctx context.Context,
	tx pgx.Tx,
	loop loopRow,
	latestRound roundRow,
	roundStatus db.Roundstatus,
) (db.Roundstatus, error) {
	_ = ctx
	_ = tx
	_ = loop
	_ = latestRound
	return roundStatus, nil
}

func (s *Service) handleNonTerminalRoundByModeTx(
	ctx context.Context,
	tx pgx.Tx,
	loop loopRow,
	roundStatus db.Roundstatus,
) error {
	policy, err := s.modeRoundPolicyFor(loop.Mode)
	if err != nil {
		return err
	}
	return policy.handleNonTerminalRoundTx(ctx, tx, s, loop, roundStatus)
}

func (s *Service) markLoopFailedByRoundTx(ctx context.Context, tx pgx.Tx, loop loopRow) error {
	return s.updateLoopRuntime(
		ctx,
		tx,
		loop.ID,
		lifecycleFailed,
		loop.Phase,
		terminalReasonSystemError,
		loop.LastConfirmedCommitID,
	)
}

func (s *Service) handleTerminalRoundByModeTx(
	ctx context.Context,
	tx pgx.Tx,
	loop loopRow,
	latestRound roundRow,
) error {
	policy, err := s.modeRoundPolicyFor(loop.Mode)
	if err != nil {
		return err
	}
	return policy.handleTerminalRoundTx(ctx, tx, s, loop, latestRound)
}

func (s *Service) handleSimulationTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	loop loopRow,
	latestRound roundRow,
) error {
	if s.shouldDelaySimulationRound(latestRound.EndedAt) {
		return nil
	}

	if s.domainClient == nil || !s.domainClient.Enabled() {
		return s.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleFailed,
			loop.Phase,
			terminalReasonSystemError,
			loop.LastConfirmedCommitID,
		)
	}

	response, err := s.domainClient.ResolveRoundReveal(
		ctx,
		loop.ID.String(),
		latestRound.ID.String(),
		loop.BranchID.String(),
		true,
		1,
	)
	if err != nil {
		if st, ok := grpcstatus.FromError(err); ok && st.Code() == codes.InvalidArgument {
			s.logger.Warn().
				Str("loop_id", loop.ID.String()).
				Str("round_id", latestRound.ID.String()).
				Str("detail", st.Message()).
				Msg("simulation reveal rejected by runtime-domain")
			return s.updateLoopRuntime(
				ctx,
				tx,
				loop.ID,
				lifecycleFailed,
				loop.Phase,
				terminalReasonSystemError,
				loop.LastConfirmedCommitID,
			)
		}
		return err
	}

	poolHiddenAfter := int(response.GetPoolHiddenAfter())
	if poolHiddenAfter < 0 {
		poolHiddenAfter = 0
	}
	revealedCount := int(response.GetRevealedCount())

	latestCommitID := loop.LastConfirmedCommitID
	latestCommitRaw := strings.TrimSpace(response.GetLatestCommitId())
	if latestCommitRaw != "" {
		parsedCommitID, parseErr := parseUUID(latestCommitRaw)
		if parseErr != nil {
			return parseErr
		}
		latestCommitID = &parsedCommitID
	}

	if poolHiddenAfter == 0 {
		return s.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleCompleted,
			phaseSimFinalize,
			terminalReasonSuccess,
			latestCommitID,
		)
	}
	if latestRound.RoundIndex >= loop.MaxRounds {
		return s.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleFailed,
			phaseSimFinalize,
			terminalReasonSystemError,
			latestCommitID,
		)
	}
	if revealedCount == 0 {
		return s.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleFailed,
			phaseSimFinalize,
			terminalReasonSystemError,
			latestCommitID,
		)
	}
	_, err = s.createNextRoundTx(ctx, tx, loop, uuid.NewString())
	return err
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
				logEvent := s.logger.Warn().
					Str("loop_id", loop.ID.String()).
					Str("step_id", stepID.String()).
					Dur("force_after", s.stopForceCancelAfter)
				if taskID, ok, mapErr := s.resolveTaskIDForStepTx(ctx, tx, stepID); mapErr == nil && ok {
					logEvent = logEvent.Str("task_id", taskID.String())
				}
				logEvent.Msg("STOPPING 超时后强制取消步骤")
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

	if err := s.updateLoopRuntime(
		ctx,
		tx,
		loop.ID,
		lifecycleStopped,
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
	_, hasRound, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return false, err
	}
	if !hasRound {
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

func (s *Service) getNextRoundAttemptIndexTx(
	ctx context.Context,
	tx pgx.Tx,
	loopID uuid.UUID,
	roundIndex int,
) (int, error) {
	next, err := s.qtx(tx).GetNextRoundAttemptIndex(ctx, db.GetNextRoundAttemptIndexParams{
		LoopID:     loopID,
		RoundIndex: int32(roundIndex),
	})
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
	createdRoundID, err := s.createRoundAttemptTx(
		ctx,
		tx,
		loop,
		nextRound,
		1,
		nil,
		"",
	)
	if err != nil {
		return false, err
	}
	return createdRoundID != nil, nil
}

func (s *Service) createRoundAttemptTx(
	ctx context.Context,
	tx pgx.Tx,
	loop loopRow,
	roundIndex int,
	attemptIndex int,
	retryOfRoundID *uuid.UUID,
	retryReason string,
) (*uuid.UUID, error) {
	if roundIndex <= 0 {
		return nil, fmt.Errorf("invalid round_index: %d", roundIndex)
	}
	if attemptIndex <= 0 {
		return nil, fmt.Errorf("invalid attempt_index: %d", attemptIndex)
	}

	sourceCommitID, projectIDFromBranch, err := s.resolveBranchHead(ctx, loop.BranchID)
	if err != nil {
		s.logger.Warn().Err(err).Str("loop_id", loop.ID.String()).Msg("解析分支头失败，继续使用空 source commit")
	}
	projectID := loop.ProjectID
	if projectIDFromBranch != nil {
		projectID = *projectIDFromBranch
	}
	if loop.Mode == modeSIM {
		oracleCommitRaw := strings.TrimSpace(extractOracleCommitID(loop.Config))
		if oracleCommitRaw == "" {
			return nil, fmt.Errorf("simulation loop missing config.mode.oracle_commit_id")
		}
		oracleCommitID, parseErr := parseUUID(oracleCommitRaw)
		if parseErr != nil {
			return nil, fmt.Errorf("invalid simulation oracle_commit_id: %w", parseErr)
		}
		sourceCommitID = &oracleCommitID
	}

	roundID := uuid.New()
	roundConfig := compileRoundConfig(loop, roundIndex)
	paramsJSON, err := marshalJSON(roundConfig)
	if err != nil {
		return nil, err
	}
	resourcesJSON := "{}"
	if resourcePayload := extractRoundResources(loop.Config); resourcePayload != nil {
		if resourcesJSON, err = marshalJSON(resourcePayload); err != nil {
			return nil, err
		}
	}

	if err := s.qtx(tx).InsertRound(ctx, db.InsertRoundParams{
		RoundID:        roundID,
		ProjectID:      projectID,
		LoopID:         loop.ID,
		RoundIndex:     int32(roundIndex),
		AttemptIndex:   int32(attemptIndex),
		Mode:           loop.Mode,
		State:          roundPending,
		StepCounts:     []byte(`{}`),
		PluginID:       loop.ModelArch,
		ResolvedParams: []byte(paramsJSON),
		Resources:      []byte(resourcesJSON),
		InputCommitID:  sourceCommitID,
		RetryOfRoundID: retryOfRoundID,
		RetryReason:    toNullablePGText(retryReason),
	}); err != nil {
		return nil, err
	}

	stepPlan := stepPlanByMode(loop.Mode)
	if len(stepPlan) == 0 {
		return nil, fmt.Errorf("unsupported loop mode for step plan: %s", loop.Mode)
	}
	var previousStepID *uuid.UUID
	for idx, stepSpec := range stepPlan {
		stepID := uuid.New()
		dependsOn := make([]uuid.UUID, 0, 1)
		if previousStepID != nil {
			dependsOn = append(dependsOn, *previousStepID)
		}
		dependsOnJSON, err := marshalJSON(dependsOn)
		if err != nil {
			return nil, err
		}
		stepConfig := compileStepConfig(roundConfig, stepSpec.StepType, loop.Mode)
		stepParamsJSON, err := marshalJSON(stepConfig)
		if err != nil {
			return nil, err
		}
		if err := s.qtx(tx).InsertStep(ctx, db.InsertStepParams{
			StepID:           stepID,
			RoundID:          roundID,
			StepType:         stepSpec.StepType,
			DispatchKind:     stepSpec.DispatchKind,
			RoundIndex:       int32(roundIndex),
			StepIndex:        int32(idx + 1),
			DependsOnStepIds: []byte(dependsOnJSON),
			ResolvedParams:   []byte(stepParamsJSON),
			InputCommitID:    sourceCommitID,
		}); err != nil {
			return nil, err
		}
		if _, bindErr := s.ensureTaskBindingForStepTx(
			ctx,
			tx,
			stepID,
			projectID,
			stepSpec.StepType,
			loop.ModelArch,
			sourceCommitID,
			[]byte(stepParamsJSON),
			3,
		); bindErr != nil {
			return nil, bindErr
		}
		previousStepID = &stepID
		if idx == 0 {
			taskID, mapped, mapErr := s.resolveTaskIDForStepTx(ctx, tx, stepID)
			if mapErr != nil {
				return nil, mapErr
			}
			if mapped {
				s.dispatcher.QueueTask(taskID.String())
			}
		}
	}

	phase := stepPlan[0].Phase

	if err := s.qtx(tx).UpdateLoopAfterRoundCreated(ctx, db.UpdateLoopAfterRoundCreatedParams{
		CurrentIteration: int32(roundIndex),
		Phase:            phase,
		LoopID:           loop.ID,
	}); err != nil {
		return nil, err
	}
	return &roundID, nil
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
	countsJSON, err := marshalJSON(stepStatusCountsForAPI(counts))
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

func stepStatusCountsForAPI(counts map[db.Stepstatus]int) map[string]int {
	if len(counts) == 0 {
		return map[string]int{}
	}
	normalized := make(map[string]int, len(counts))
	for state, count := range counts {
		key := strings.ToLower(strings.TrimSpace(string(state)))
		if key == "" {
			continue
		}
		normalized[key] += count
	}
	return normalized
}

func summarizeRoundState(counts map[db.Stepstatus]int, total int) db.Roundstatus {
	if total <= 0 {
		return roundPending
	}
	failed := counts[stepFailed]
	cancelled := counts[stepCancelled]
	running := counts[stepRunning] +
		counts[stepBindingDev] +
		counts[stepProbingRt] +
		counts[stepSyncingEnv] +
		counts[stepDispatching] +
		counts[stepRetrying]
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

func (s *Service) updateLoopLifecycle(ctx context.Context, tx pgx.Tx, loopID uuid.UUID, lifecycle db.Looplifecycle) error {
	currentLifecycle, err := s.qtx(tx).GetLoopLifecycle(ctx, loopID)
	if err != nil {
		return err
	}
	target := lifecycle
	if !canLoopLifecycleTransition(currentLifecycle, target) {
		return fmt.Errorf("非法 loop lifecycle迁移: %s -> %s", currentLifecycle, target)
	}
	affected, err := s.qtx(tx).UpdateLoopLifecycleGuarded(ctx, db.UpdateLoopLifecycleGuardedParams{
		Lifecycle:     target,
		LoopID:        loopID,
		FromLifecycle: currentLifecycle,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop lifecycle迁移冲突: %s -> %s", currentLifecycle, target)
	}
	return nil
}

func (s *Service) updateLoopRuntime(
	ctx context.Context,
	tx pgx.Tx,
	loopID uuid.UUID,
	lifecycle db.Looplifecycle,
	phase db.Loopphase,
	terminalReason string,
	lastConfirmedCommitID *uuid.UUID,
) error {
	currentLifecycle, err := s.qtx(tx).GetLoopLifecycle(ctx, loopID)
	if err != nil {
		return err
	}
	target := lifecycle
	if !canLoopLifecycleTransition(currentLifecycle, target) {
		return fmt.Errorf("非法 loop lifecycle迁移: %s -> %s", currentLifecycle, target)
	}
	affected, err := s.qtx(tx).UpdateLoopRuntimeGuarded(ctx, db.UpdateLoopRuntimeGuardedParams{
		Lifecycle:             target,
		Phase:                 phase,
		TerminalReason:        toNullablePGText(terminalReason),
		LastConfirmedCommitID: lastConfirmedCommitID,
		LoopID:                loopID,
		FromLifecycle:         currentLifecycle,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("loop lifecycle写入冲突: %s -> %s", currentLifecycle, target)
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

func (s *Service) getLoopByID(ctx context.Context, loopID uuid.UUID) (loopRow, bool, error) {
	if !s.dbEnabled() {
		return loopRow{}, false, nil
	}
	record, err := s.queries.GetLoopByID(ctx, loopID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return loopRow{}, false, nil
		}
		return loopRow{}, false, err
	}
	return mapLoopByID(record), true, nil
}

func (s *Service) preflightALConfirmReveal(
	ctx context.Context,
	loopID uuid.UUID,
	force bool,
) (*alConfirmRevealProbe, error) {
	if s.domainClient == nil || !s.domainClient.Enabled() {
		return nil, nil
	}
	loop, found, err := s.getLoopByID(ctx, loopID)
	if err != nil || !found {
		return nil, err
	}
	if loop.Mode != modeAL || loop.Phase != phaseALWaitAnnotation {
		return nil, nil
	}

	latestRoundRecord, err := s.queries.GetLatestRoundByLoop(ctx, loopID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}

	minRequired := loop.MinNewLabelsPerRound
	if minRequired <= 0 {
		minRequired = 1
	}
	response, err := s.domainClient.ResolveRoundReveal(
		ctx,
		loop.ID.String(),
		latestRoundRecord.ID.String(),
		loop.BranchID.String(),
		force,
		int32(minRequired),
	)
	if err != nil {
		return nil, err
	}

	var latestCommitID *uuid.UUID
	latestCommitRaw := strings.TrimSpace(response.GetLatestCommitId())
	if latestCommitRaw != "" {
		parsedCommitID, parseErr := parseUUID(latestCommitRaw)
		if parseErr != nil {
			return nil, parseErr
		}
		latestCommitID = &parsedCommitID
	}
	return &alConfirmRevealProbe{
		roundID:               latestRoundRecord.ID,
		branchID:              loop.BranchID,
		configuredMinRequired: minRequired,
		revealedCount:         int(response.GetRevealedCount()),
		selectedCount:         int(response.GetSelectedCount()),
		effectiveMinRequired:  int(response.GetEffectiveMinRequired()),
		latestCommitID:        latestCommitID,
	}, nil
}

func (s *Service) resolveBranchHead(ctx context.Context, branchID uuid.UUID) (headCommitID *uuid.UUID, projectID *uuid.UUID, err error) {
	if s.dbEnabled() {
		row, queryErr := s.queries.ResolveBranchHeadFromDB(ctx, branchID)
		if queryErr == nil {
			return &row.HeadCommitID, &row.ProjectID, nil
		}
		if queryErr != pgx.ErrNoRows {
			return nil, nil, queryErr
		}
	}

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
	return nil, nil, nil
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
	return max(0, latestCount-sinceCount), headCommitID, nil
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
