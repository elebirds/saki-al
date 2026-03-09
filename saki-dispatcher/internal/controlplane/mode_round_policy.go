package controlplane

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

type modeRoundPolicy interface {
	handleNonTerminalRoundTx(
		ctx context.Context,
		tx pgx.Tx,
		service *Service,
		loop loopRow,
		roundStatus db.Roundstatus,
	) error
	handleTerminalRoundTx(
		ctx context.Context,
		tx pgx.Tx,
		service *Service,
		loop loopRow,
		latestRound roundRow,
	) error
}

func (s *Service) modeRoundPolicyFor(mode db.Loopmode) (modeRoundPolicy, error) {
	switch mode {
	case modeAL:
		return alModeRoundPolicy{}, nil
	case modeSIM:
		return simModeRoundPolicy{}, nil
	case modeManual:
		return manualModeRoundPolicy{}, nil
	default:
		return nil, fmt.Errorf("unsupported loop mode: %s", mode)
	}
}

type alModeRoundPolicy struct{}

func (alModeRoundPolicy) handleNonTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	roundStatus db.Roundstatus,
) error {
	_ = ctx
	_ = tx
	_ = service
	_ = loop
	_ = roundStatus
	return nil
}

func (alModeRoundPolicy) handleTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	latestRound roundRow,
) error {
	if latestRound.SummaryStatus != roundCompleted {
		return nil
	}
	if loop.Lifecycle == lifecycleRunning && loop.Phase == phaseALWaitAnnotation {
		return nil
	}
	return service.updateLoopRuntime(ctx, tx, loop.ID, lifecycleRunning, phaseALWaitAnnotation, "", loop.LastConfirmedCommitID, nil)
}

type simModeRoundPolicy struct{}

func (simModeRoundPolicy) handleNonTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	roundStatus db.Roundstatus,
) error {
	_ = ctx
	_ = tx
	_ = service
	_ = loop
	_ = roundStatus
	return nil
}

func (simModeRoundPolicy) handleTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	latestRound roundRow,
) error {
	return service.handleSimulationTerminalRoundTx(ctx, tx, loop, latestRound)
}

type manualModeRoundPolicy struct{}

func (manualModeRoundPolicy) handleNonTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	roundStatus db.Roundstatus,
) error {
	_ = ctx
	_ = tx
	_ = service
	_ = loop
	_ = roundStatus
	return nil
}

func (manualModeRoundPolicy) handleTerminalRoundTx(
	ctx context.Context,
	tx pgx.Tx,
	service *Service,
	loop loopRow,
	latestRound roundRow,
) error {
	if latestRound.RoundIndex >= loop.MaxRounds {
		return service.updateLoopRuntime(
			ctx,
			tx,
			loop.ID,
			lifecycleCompleted,
			phaseManualFinalize,
			terminalReasonSuccess,
			loop.LastConfirmedCommitID,
			nil,
		)
	}
	if loop.Lifecycle == lifecycleRunning && loop.Phase == phaseManualEval {
		return nil
	}
	return service.updateLoopRuntime(ctx, tx, loop.ID, lifecycleRunning, phaseManualEval, "", loop.LastConfirmedCommitID, nil)
}
