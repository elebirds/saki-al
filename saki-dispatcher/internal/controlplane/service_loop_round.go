package controlplane

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

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
				loopPGID, err := toPGUUID(loop.ID)
				if err != nil {
					return "", "", err
				}
				commitPGID, err := toPGUUID(latestCommitID)
				if err != nil {
					return "", "", err
				}
				if err := s.qtx(tx).UpdateLoopLastConfirmedCommit(ctx, db.UpdateLoopLastConfirmedCommitParams{
					LastConfirmedCommitID: commitPGID,
					LoopID:                loopPGID,
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
		roundPGID, err := toPGUUID(roundID)
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
		currentStatus := asString(currentStatusRaw)
		if _, ok := terminalRoundStatuses[currentStatus]; ok {
			return "applied", "round already in terminal state", nil
		}

		affected, err := s.qtx(tx).UpdateRoundStateWithReasonGuarded(ctx, db.UpdateRoundStateWithReasonGuardedParams{
			State:          db.Roundstatus(roundCancelled),
			TerminalReason: toPGText(reason),
			RoundID:        roundPGID,
			FromState:      db.Roundstatus(currentStatus),
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
		stepPGID, err := toPGUUID(stepID)
		if err != nil {
			return "rejected", "step not found", nil
		}
		currentStatusRaw, err := s.qtx(tx).GetStepState(ctx, stepPGID)
		currentStatus := asString(currentStatusRaw)
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
			s.logger.Warn().Str("loop_id", loopID).Err(err).Msg("process loop failed")
		}
	}
	_, err = s.dispatchPending(ctx, 256)
	return err
}
