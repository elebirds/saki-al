package controlplane

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/encoding/protojson"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

func (s *Service) dispatchPending(ctx context.Context, limit int) (int, error) {
	if !s.dbEnabled() {
		return 0, nil
	}
	if s.dispatchLockKey != 0 {
		conn, err := s.pool.Acquire(ctx)
		if err != nil {
			return 0, err
		}
		defer conn.Release()
		connQueries := db.New(conn.Conn())

		locked, err := connQueries.TryDispatchAdvisoryLock(ctx, s.dispatchLockKey)
		if err != nil {
			return 0, err
		}
		if !locked {
			return 0, nil
		}
		defer func() {
			if _, err := connQueries.ReleaseDispatchAdvisoryLock(context.Background(), s.dispatchLockKey); err != nil {
				s.logger.Warn().Err(err).Msg("release dispatch advisory lock failed")
			}
		}()
	}

	if err := s.recoverDispatchOutbox(ctx, max(64, limit*2)); err != nil {
		return 0, err
	}

	claimed := 0
	for _, queuedStepID := range s.dispatcher.DrainQueuedStepIDs() {
		dispatched, err := s.dispatchStepByID(ctx, queuedStepID)
		if err != nil {
			return claimed, err
		}
		if dispatched {
			claimed++
		}
	}

	if _, err := s.promotePendingStepsToReady(ctx, max(64, limit*2)); err != nil {
		return claimed, err
	}
	stepIDs, err := s.listReadyStepIDs(ctx, limit)
	if err != nil {
		return claimed, err
	}
	for _, stepID := range stepIDs {
		dispatched, err := s.dispatchStepByID(ctx, stepID)
		if err != nil {
			return claimed, err
		}
		if dispatched {
			claimed++
		}
	}

	sent, err := s.dispatchOutboxBatch(ctx, max(64, limit*2))
	if err != nil {
		return claimed, err
	}
	if sent > 0 {
		s.logger.Debug().Int("claimed", claimed).Int("sent", sent).Msg("dispatch outbox drained")
	}
	return claimed + sent, nil
}

func (s *Service) promotePendingStepsToReady(ctx context.Context, limit int) (int, error) {
	stepIDs, err := s.listPendingStepIDs(ctx, limit)
	if err != nil {
		return 0, err
	}
	count := 0
	for _, stepID := range stepIDs {
		promoted, err := s.promotePendingStepIfReady(ctx, stepID)
		if err != nil {
			return count, err
		}
		if promoted {
			count++
		}
	}
	return count, nil
}

func (s *Service) promotePendingStepIfReady(ctx context.Context, stepID string) (bool, error) {
	tx, err := s.beginTx(ctx)
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
	loopPGID, err := toPGUUID(stepPayload.LoopID)
	if err != nil {
		return false, tx.Commit(ctx)
	}
	loopStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return false, tx.Commit(ctx)
		}
		return false, err
	}
	if loopStatus != db.LoopstatusRUNNING {
		return false, tx.Commit(ctx)
	}
	depsOK, err := s.dependenciesSatisfiedTx(ctx, tx, stepPayload.DependsOnStepIDs)
	if err != nil {
		return false, err
	}
	if !depsOK {
		return false, tx.Commit(ctx)
	}
	updated, err := s.promoteStepToReadyTx(ctx, tx, stepPayload.StepID)
	if err != nil {
		return false, err
	}
	if err := tx.Commit(ctx); err != nil {
		return false, err
	}
	return updated, nil
}

func (s *Service) dispatchStepByID(ctx context.Context, stepID string) (bool, error) {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	stepPayload, ok, err := s.getStepPayloadByIDTx(ctx, tx, stepID)
	if err != nil {
		return false, err
	}
	if !ok {
		return false, tx.Commit(ctx)
	}

	if stepPayload.Status == stepPending {
		loopPGID, err := toPGUUID(stepPayload.LoopID)
		if err != nil {
			return false, tx.Commit(ctx)
		}
		loopStatus, err := s.qtx(tx).GetLoopStatus(ctx, loopPGID)
		if err != nil {
			if err == pgx.ErrNoRows {
				return false, tx.Commit(ctx)
			}
			return false, err
		}
		if loopStatus != db.LoopstatusRUNNING {
			return false, tx.Commit(ctx)
		}
		depsOK, err := s.dependenciesSatisfiedTx(ctx, tx, stepPayload.DependsOnStepIDs)
		if err != nil {
			return false, err
		}
		if !depsOK {
			return false, tx.Commit(ctx)
		}
		promoted, err := s.promoteStepToReadyTx(ctx, tx, stepPayload.StepID)
		if err != nil {
			return false, err
		}
		if !promoted {
			return false, tx.Commit(ctx)
		}
		stepPayload.Status = stepReady
	}

	if stepPayload.Status != stepReady {
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
	payloadRaw, err := protojson.Marshal(message)
	if err != nil {
		return false, err
	}
	outboxID, err := toPGUUID(uuid.NewString())
	if err != nil {
		return false, err
	}
	stepPGID, err := toPGUUID(stepPayload.StepID)
	if err != nil {
		return false, err
	}
	inserted, err := s.qtx(tx).InsertDispatchOutbox(ctx, db.InsertDispatchOutboxParams{
		OutboxID:   outboxID,
		StepID:     stepPGID,
		ExecutorID: executorID,
		RequestID:  requestID,
		Payload:    payloadRaw,
	})
	if err != nil {
		return false, err
	}
	if inserted == 0 {
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
	stepPGID, err := toPGUUID(stepPayload.StepID)
	if err != nil {
		return false, err
	}
	started, err := s.qtx(tx).MarkOrchestratorStepRunning(ctx, stepPGID)
	if err != nil {
		return false, err
	}
	if started == 0 {
		return false, nil
	}

	resultStatus := stepSucceeded
	lastError := ""
	resultCommitID := ""
	if err := s.runOrchestratorStepTx(ctx, tx, stepPayload, &resultCommitID); err != nil {
		resultStatus = stepFailed
		lastError = err.Error()
	}
	resultCommitPGID, err := toNullablePGUUID(resultCommitID)
	if err != nil {
		return false, err
	}

	affected, err := s.qtx(tx).UpdateStepExecutionResultGuarded(ctx, db.UpdateStepExecutionResultGuardedParams{
		State:          db.Stepstatus(resultStatus),
		LastError:      toNullablePGText(lastError),
		OutputCommitID: resultCommitPGID,
		StepID:         stepPGID,
		FromState:      db.StepstatusRUNNING,
	})
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, nil
	}

	if strings.TrimSpace(resultCommitID) != "" {
		roundPGID, err := toPGUUID(stepPayload.RoundID)
		if err != nil {
			return false, err
		}
		if err := s.qtx(tx).UpdateRoundOutputCommit(ctx, db.UpdateRoundOutputCommitParams{
			OutputCommitID: resultCommitPGID,
			RoundID:        roundPGID,
		}); err != nil {
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
	loopPGID, err := toPGUUID(stepPayload.LoopID)
	if err != nil {
		return err
	}
	roundPGID, err := toPGUUID(stepPayload.RoundID)
	if err != nil {
		return err
	}
	stepPGID, err := toPGUUID(stepPayload.StepID)
	if err != nil {
		return err
	}
	queryBatchRaw, err := s.qtx(tx).GetLoopQueryBatchSize(ctx, loopPGID)
	if err != nil {
		return err
	}
	queryBatch := int(queryBatchRaw)
	if queryBatch <= 0 {
		queryBatch = 1
	}

	scoreStepID, err := s.qtx(tx).GetSucceededScoreStepIDByRound(ctx, roundPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("score step not ready for select step %s", stepPayload.StepID)
		}
		return err
	}
	scoreStepPGID, err := toPGUUID(scoreStepID)
	if err != nil {
		return err
	}
	rows, err := s.qtx(tx).ListStepCandidatesByStepID(ctx, db.ListStepCandidatesByStepIDParams{
		StepID:     scoreStepPGID,
		LimitCount: int32(queryBatch),
	})
	if err != nil {
		return err
	}

	type candidateRow struct {
		sampleID       string
		score          float64
		reasonJSON     string
		predictionJSON string
	}
	candidates := make([]candidateRow, 0, queryBatch)
	for _, row := range rows {
		candidates = append(candidates, candidateRow{
			sampleID:       row.SampleID,
			score:          row.Score,
			reasonJSON:     asString(row.ReasonJson),
			predictionJSON: asString(row.PredictionJson),
		})
	}
	if err := s.qtx(tx).DeleteStepCandidatesByStepID(ctx, stepPGID); err != nil {
		return err
	}
	copyRows := make([]db.CopyStepCandidateItemsParams, 0, len(candidates))
	now := toPGTimestamp(time.Now().UTC())
	for idx, item := range candidates {
		parsedSampleID, err := toPGUUID(item.sampleID)
		if err != nil {
			continue
		}
		candidateID, err := toPGUUID(uuid.NewString())
		if err != nil {
			return err
		}
		copyRows = append(copyRows, db.CopyStepCandidateItemsParams{
			ID:                 candidateID,
			StepID:             stepPGID,
			SampleID:           parsedSampleID,
			Rank:               int32(idx + 1),
			Score:              item.score,
			Reason:             []byte(item.reasonJSON),
			PredictionSnapshot: []byte(item.predictionJSON),
			CreatedAt:          now,
			UpdatedAt:          now,
		})
	}
	if len(copyRows) > 0 {
		if _, err := s.qtx(tx).CopyStepCandidateItems(ctx, copyRows); err != nil {
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
	loopPGID, err := toPGUUID(stepPayload.LoopID)
	if err != nil {
		return err
	}
	loopConfig, err := s.qtx(tx).GetLoopRuntimeConfig(ctx, loopPGID)
	if err != nil {
		return err
	}
	projectID = asString(loopConfig.ProjectID)
	branchID = asString(loopConfig.BranchID)
	queryStrategy = loopConfig.QueryStrategy
	globalConfig = asString(loopConfig.GlobalConfig)
	queryBatch = int(loopConfig.QueryBatchSize)

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
	loopPGID, err := toPGUUID(stepPayload.LoopID)
	if err != nil {
		return err
	}
	branchIDRaw, err := s.qtx(tx).GetLoopBranchID(ctx, loopPGID)
	if err != nil {
		return err
	}
	branchID = strings.TrimSpace(asString(branchIDRaw))
	if branchID == "" {
		return fmt.Errorf("loop %s branch_id is empty", stepPayload.LoopID)
	}

	var activateCommitID string
	roundPGID, err := toPGUUID(stepPayload.RoundID)
	if err != nil {
		return err
	}
	activateCommitRaw, err := s.qtx(tx).GetLatestActivateOutputCommitByRound(ctx, roundPGID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("activate_samples output commit not found for round %s", stepPayload.RoundID)
		}
		return err
	}
	activateCommitID = strings.TrimSpace(asString(activateCommitRaw))
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
