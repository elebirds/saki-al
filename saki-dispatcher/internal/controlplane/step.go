package controlplane

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	runtimedomainv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimedomainv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
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
				s.logger.Warn().Err(err).Msg("释放派发 advisory 锁失败")
			}
		}()
	}

	if err := s.recoverDispatchOutbox(ctx, max(64, limit*2)); err != nil {
		return 0, err
	}

	claimed := 0
	for _, queuedStepID := range s.dispatcher.DrainQueuedStepIDs() {
		stepID, err := parseUUID(queuedStepID)
		if err != nil {
			continue
		}
		dispatched, err := s.dispatchStepByID(ctx, stepID)
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
	if _, err := s.promoteRetryingStepsToReady(ctx, max(64, limit*2)); err != nil {
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
		s.logger.Debug().Int("claimed", claimed).Int("sent", sent).Msg("派发 outbox 已清空")
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

func (s *Service) promoteRetryingStepsToReady(ctx context.Context, limit int) (int, error) {
	stepIDs, err := s.listRetryingStepIDsDue(ctx, limit)
	if err != nil {
		return 0, err
	}
	count := 0
	for _, stepID := range stepIDs {
		promoted, err := s.promoteRetryingStepToReady(ctx, stepID)
		if err != nil {
			return count, err
		}
		if promoted {
			count++
		}
	}
	return count, nil
}

func (s *Service) promoteRetryingStepToReady(ctx context.Context, stepID uuid.UUID) (bool, error) {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	updated, err := s.promoteRetryingStepToReadyTx(ctx, tx, stepID)
	if err != nil {
		return false, err
	}
	if err := tx.Commit(ctx); err != nil {
		return false, err
	}
	return updated, nil
}

func (s *Service) promotePendingStepIfReady(ctx context.Context, stepID uuid.UUID) (bool, error) {
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
	loopStatus, err := s.qtx(tx).GetLoopStatus(ctx, stepPayload.LoopID)
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

func (s *Service) dispatchStepByID(ctx context.Context, stepID uuid.UUID) (bool, error) {
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
		loopStatus, err := s.qtx(tx).GetLoopStatus(ctx, stepPayload.LoopID)
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
		now := time.Now().UTC()
		stepPayload.UpdatedAt = &now
	}

	if stepPayload.Status != stepReady {
		return false, tx.Commit(ctx)
	}
	if err := s.syncLoopPhaseWithStepTx(ctx, tx, stepPayload); err != nil {
		return false, err
	}
	if isOrchestratorDispatchKind(stepPayload.DispatchKind) {
		executed, err := s.executeOrchestratorStepTx(ctx, tx, stepPayload)
		if err != nil {
			return false, err
		}
		return executed, tx.Commit(ctx)
	}

	preferredExecutorID, err := s.resolvePreferredExecutorIDByDependenciesTx(ctx, tx, stepPayload.DependsOnStepIDs)
	if err != nil {
		return false, err
	}
	executorID, deferredByAffinity := s.pickExecutorWithRoundAffinity(
		stepPayload.PluginID,
		preferredExecutorID,
		stepPayload.UpdatedAt,
	)
	if deferredByAffinity || strings.TrimSpace(executorID) == "" {
		return false, tx.Commit(ctx)
	}

	resolvedParams, err := s.buildDispatchResolvedParamsTx(ctx, tx, stepPayload)
	if err != nil {
		if !s.strictModelHandoff {
			s.logger.Warn().
				Err(err).
				Str("step_id", stepPayload.StepID.String()).
				Str("step_type", strings.ToLower(string(stepPayload.StepType))).
				Msg("训练模型交接失败，STRICT_TRAIN_MODEL_HANDOFF=false，回退旧行为")
			resolvedParams = stepPayload.Params
		} else {
			reason := strings.TrimSpace(err.Error())
			if reason == "" {
				reason = "训练模型交接失败"
			}
			if failErr := s.failStepDispatchPreflightTx(ctx, tx, stepPayload.StepID, reason); failErr != nil {
				return false, failErr
			}
			if _, refreshErr := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); refreshErr != nil {
				return false, refreshErr
			}
			s.logger.Warn().
				Str("step_id", stepPayload.StepID.String()).
				Str("step_type", strings.ToLower(string(stepPayload.StepType))).
				Msgf("训练模型交接失败，步骤已标记 FAILED: %s", reason)
			return true, tx.Commit(ctx)
		}
	}

	requestID := uuid.NewString()
	updated, err := s.markStepDispatchingTx(ctx, tx, stepPayload.StepID, executorID, requestID)
	if err != nil {
		return false, err
	}
	if !updated {
		return false, tx.Commit(ctx)
	}

	inputCommitID := ""
	if stepPayload.InputCommitID != nil {
		inputCommitID = stepPayload.InputCommitID.String()
	}
	dependsOnStepIDs := uuidSliceToStringSlice(stepPayload.DependsOnStepIDs)
	message := &runtimecontrolv1.StepPayload{
		StepId:           stepPayload.StepID.String(),
		RoundId:          stepPayload.RoundID.String(),
		LoopId:           stepPayload.LoopID.String(),
		ProjectId:        stepPayload.ProjectID.String(),
		InputCommitId:    inputCommitID,
		StepType:         toRuntimeStepType(stepPayload.StepType),
		DispatchKind:     toRuntimeStepDispatchKind(stepPayload.DispatchKind),
		PluginId:         stepPayload.PluginID,
		Mode:             toRuntimeLoopMode(stepPayload.Mode),
		QueryStrategy:    extractSamplingStrategyFromStruct(resolvedParams),
		ResolvedParams:   resolvedParams,
		Resources:        stepPayload.Resources,
		RoundIndex:       int32(stepPayload.RoundIndex),
		Attempt:          int32(stepPayload.Attempt),
		DependsOnStepIds: dependsOnStepIDs,
	}
	payloadRaw, err := protojson.Marshal(message)
	if err != nil {
		return false, err
	}
	outboxID := uuid.New()
	inserted, err := s.qtx(tx).InsertDispatchOutbox(ctx, db.InsertDispatchOutboxParams{
		OutboxID:   outboxID,
		StepID:     stepPayload.StepID,
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

func (s *Service) syncLoopPhaseWithStepTx(ctx context.Context, tx pgx.Tx, stepPayload stepDispatchPayload) error {
	nextPhase, ok := phaseForStep(stepPayload.Mode, stepPayload.StepType)
	if !ok {
		return nil
	}
	_, err := s.qtx(tx).UpdateLoopPhaseIfRunning(ctx, db.UpdateLoopPhaseIfRunningParams{
		Phase:  nextPhase,
		LoopID: stepPayload.LoopID,
	})
	return err
}

func isOrchestratorDispatchKind(dispatchKind db.Stepdispatchkind) bool {
	return dispatchKind == db.StepdispatchkindORCHESTRATOR
}

func (s *Service) executeOrchestratorStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
) (bool, error) {
	started, err := s.qtx(tx).MarkOrchestratorStepRunning(ctx, stepPayload.StepID)
	if err != nil {
		return false, err
	}
	if started == 0 {
		return false, nil
	}

	resultStatus := stepSucceeded
	lastError := ""
	var resultCommitID *uuid.UUID
	if err := s.runOrchestratorStepTx(ctx, tx, stepPayload, &resultCommitID); err != nil {
		lastError = strings.TrimSpace(err.Error())
		if lastError == "" {
			lastError = "编排步骤执行失败"
		}
		if runtime_domain_client.IsTransientError(err) {
			retried, retryErr := s.markOrchestratorStepRetryingTx(ctx, tx, stepPayload.StepID, lastError)
			if retryErr != nil {
				return false, retryErr
			}
			if retried {
				if _, refreshErr := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); refreshErr != nil {
					return false, refreshErr
				}
				return true, nil
			}
			lastError = fmt.Sprintf("临时错误且超过最大重试次数: %s", lastError)
		}
		resultStatus = stepFailed
	}

	affected, err := s.qtx(tx).UpdateStepExecutionResultGuarded(ctx, db.UpdateStepExecutionResultGuardedParams{
		State:          resultStatus,
		LastError:      toNullablePGText(lastError),
		OutputCommitID: resultCommitID,
		StepID:         stepPayload.StepID,
		FromState:      db.StepstatusRUNNING,
	})
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, nil
	}

	if resultCommitID != nil {
		if err := s.qtx(tx).UpdateRoundOutputCommit(ctx, db.UpdateRoundOutputCommitParams{
			OutputCommitID: resultCommitID,
			RoundID:        stepPayload.RoundID,
		}); err != nil {
			return false, err
		}
	}

	if _, err := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) markOrchestratorStepRetryingTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	reason string,
) (bool, error) {
	affected, err := s.qtx(tx).MarkOrchestratorStepRetrying(ctx, db.MarkOrchestratorStepRetryingParams{
		LastError: toPGText(reason),
		StepID:    stepID,
	})
	if err != nil {
		return false, err
	}
	return affected > 0, nil
}

func (s *Service) runOrchestratorStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
	resultCommitID **uuid.UUID,
) error {
	switch stepPayload.StepType {
	case db.SteptypeSELECT:
		return s.runSelectTopKTx(ctx, tx, stepPayload)
	case db.SteptypeACTIVATESAMPLES:
		return s.runActivateSamplesTx(ctx, tx, stepPayload, resultCommitID)
	case db.SteptypeADVANCEBRANCH:
		return s.runAdvanceBranchTx(ctx, tx, stepPayload, resultCommitID)
	default:
		return fmt.Errorf("unsupported orchestrator step type: %s", stepPayload.StepType)
	}
}

func (s *Service) runSelectTopKTx(ctx context.Context, tx pgx.Tx, stepPayload stepDispatchPayload) error {
	queryBatchRaw, err := s.qtx(tx).GetLoopQueryBatchSize(ctx, stepPayload.LoopID)
	if err != nil {
		return err
	}
	queryBatch := int(queryBatchRaw)
	if queryBatch <= 0 {
		queryBatch = 1
	}

	scoreStepID, err := s.qtx(tx).GetSucceededScoreStepIDByRound(ctx, stepPayload.RoundID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("SELECT 步骤依赖的 SCORE 结果尚未就绪: step_id=%s", stepPayload.StepID)
		}
		return err
	}
	rows, err := s.qtx(tx).ListStepCandidatesByStepID(ctx, db.ListStepCandidatesByStepIDParams{
		StepID:     scoreStepID,
		LimitCount: int32(queryBatch),
	})
	if err != nil {
		return err
	}

	type candidateRow struct {
		sampleID       uuid.UUID
		score          float64
		reasonJSON     []byte
		predictionJSON []byte
	}
	candidates := make([]candidateRow, 0, queryBatch)
	for _, row := range rows {
		candidates = append(candidates, candidateRow{
			sampleID:       row.SampleID,
			score:          row.Score,
			reasonJSON:     row.ReasonJson,
			predictionJSON: row.PredictionJson,
		})
	}
	if err := s.qtx(tx).DeleteStepCandidatesByStepID(ctx, stepPayload.StepID); err != nil {
		return err
	}
	copyRows := make([]db.CopyStepCandidateItemsParams, 0, len(candidates))
	now := toPGTimestamp(time.Now().UTC())
	for idx, item := range candidates {
		copyRows = append(copyRows, db.CopyStepCandidateItemsParams{
			ID:                 uuid.New(),
			StepID:             stepPayload.StepID,
			SampleID:           item.sampleID,
			Rank:               int32(idx + 1),
			Score:              item.score,
			Reason:             item.reasonJSON,
			PredictionSnapshot: item.predictionJSON,
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
	resultCommitID **uuid.UUID,
) error {
	if s.domainClient == nil {
		return fmt.Errorf("runtime_domain 客户端未初始化")
	}
	if !s.domainClient.Configured() {
		return runtime_domain_client.ErrNotConfigured
	}
	if !s.domainClient.Enabled() {
		return runtime_domain_client.ErrDisabled
	}

	var (
		projectID  string
		branchID   string
		loopConfig map[string]any
		queryBatch int
	)
	loopRuntimeConfig, err := s.qtx(tx).GetLoopRuntimeConfig(ctx, stepPayload.LoopID)
	if err != nil {
		return err
	}
	projectID = loopRuntimeConfig.ProjectID.String()
	branchID = loopRuntimeConfig.BranchID.String()
	queryBatch = int(loopRuntimeConfig.QueryBatchSize)
	loopConfig, _ = parseJSONObject(loopRuntimeConfig.Config)

	oracleCommitID := extractOracleCommitID(loopRuntimeConfig.Config)
	if oracleCommitID == "" {
		return nil
	}

	sourceCommitID := ""
	if stepPayload.InputCommitID != nil {
		sourceCommitID = stepPayload.InputCommitID.String()
	}
	if sourceCommitID == "" {
		headCommitID, branchProjectID, err := s.resolveBranchHead(ctx, loopRuntimeConfig.BranchID)
		if err != nil {
			return err
		}
		if headCommitID != nil {
			sourceCommitID = headCommitID.String()
		}
		if branchProjectID != nil {
			projectID = branchProjectID.String()
		}
	}

	queryStrategy, topk := extractSamplingStrategyAndTopK(loopConfig, stepPayload.Params, queryBatch)
	if topk <= 0 {
		topk = 1
	}

	commandID := activationCommandID(stepPayload)
	response, err := s.domainClient.ActivateSamples(ctx, &runtimedomainv1.ActivateSamplesRequest{
		CommandId:      commandID,
		ProjectId:      projectID,
		BranchId:       branchID,
		OracleCommitId: oracleCommitID,
		SourceCommitId: sourceCommitID,
		LoopId:         stepPayload.LoopID.String(),
		RoundIndex:     int32(stepPayload.RoundIndex),
		QueryStrategy:  queryStrategy,
		Topk:           int32(topk),
	})
	if err != nil {
		return err
	}
	commitID := strings.TrimSpace(response.GetCommitId())
	if commitID != "" {
		if resultCommitID != nil {
			parsedID, parseErr := parseUUID(commitID)
			if parseErr != nil {
				return parseErr
			}
			*resultCommitID = &parsedID
		}
	}
	return nil
}

func (s *Service) runAdvanceBranchTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
	resultCommitID **uuid.UUID,
) error {
	if s.domainClient == nil {
		return fmt.Errorf("runtime_domain 客户端未初始化")
	}
	if !s.domainClient.Configured() {
		return runtime_domain_client.ErrNotConfigured
	}
	if !s.domainClient.Enabled() {
		return runtime_domain_client.ErrDisabled
	}

	branchID, err := s.qtx(tx).GetLoopBranchID(ctx, stepPayload.LoopID)
	if err != nil {
		return err
	}
	if branchID == uuid.Nil {
		return fmt.Errorf("loop 的 branch_id 为空: loop_id=%s", stepPayload.LoopID)
	}

	activateCommitID, err := s.qtx(tx).GetLatestActivateOutputCommitByRound(ctx, stepPayload.RoundID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("round 缺少 ACTIVATE_SAMPLES 输出 commit: round_id=%s", stepPayload.RoundID)
		}
		return err
	}
	if activateCommitID == nil {
		return fmt.Errorf("ACTIVATE_SAMPLES 输出 commit 为空: round_id=%s", stepPayload.RoundID)
	}

	commandID := advanceBranchCommandID(stepPayload, *activateCommitID)
	response, err := s.domainClient.AdvanceBranchHead(
		ctx,
		commandID,
		branchID.String(),
		activateCommitID.String(),
		fmt.Sprintf("loop=%s round=%d advance_branch_step=%s", stepPayload.LoopID, stepPayload.RoundIndex, stepPayload.StepID),
	)
	if err != nil {
		return err
	}
	if !response.GetAdvanced() {
		headCommitID := strings.TrimSpace(response.GetHeadCommitId())
		if headCommitID == activateCommitID.String() {
			if resultCommitID != nil {
				*resultCommitID = activateCommitID
			}
			return nil
		}
		return fmt.Errorf("推进分支头被拒绝: branch_id=%s commit_id=%s head_commit_id=%s", branchID, activateCommitID, headCommitID)
	}
	if resultCommitID != nil {
		*resultCommitID = activateCommitID
	}
	return nil
}

func (s *Service) OnStepEvent(ctx context.Context, event *runtimecontrolv1.StepEvent) error {
	if !s.dbEnabled() || event == nil {
		return nil
	}
	stepID, err := parseUUID(event.GetStepId())
	if err != nil {
		return nil
	}

	eventType, eventPayload, statusValue := decodeStepEvent(event)
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
		targetState := statusValue
		if targetState == stepPending || !shouldApplyRuntimeStatus(targetState) {
			break
		}
		affected, err := s.updateStepStatusFromEventGuardedTx(
			ctx,
			tx,
			stepID,
			targetState,
			strings.TrimSpace(event.GetStatusEvent().GetReason()),
		)
		if err != nil {
			return err
		}
		if affected == 0 {
			return fmt.Errorf("运行时事件导致非法步骤迁移: step_id=%s target=%s", stepID, targetState)
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
	if roundID != nil {
		if _, err := s.refreshRoundAggregateTx(ctx, tx, *roundID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Service) OnStepResult(ctx context.Context, result *runtimecontrolv1.StepResult) error {
	if !s.dbEnabled() || result == nil {
		return nil
	}
	stepID, err := parseUUID(result.GetStepId())
	if err != nil {
		return nil
	}
	targetState := runtimeStatusToStepStatus(result.GetStatus())
	if targetState == "" {
		targetState = stepFailed
	}

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

	affected, err := s.updateStepResultGuardedTx(ctx, tx, stepID, targetState, []byte(metricsJSON), []byte(artifactsJSON), strings.TrimSpace(result.GetErrorMessage()))
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("步骤结果导致非法状态迁移: step_id=%s target=%s", stepID, targetState)
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
	if roundID != nil {
		if _, err := s.refreshRoundAggregateTx(ctx, tx, *roundID); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Service) updateStepStatusFromEventGuardedTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
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
	stepID uuid.UUID,
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

func (s *Service) listPendingStepIDs(ctx context.Context, limit int) ([]uuid.UUID, error) {
	return s.queries.ListPendingStepIDs(ctx, int32(max(1, limit)))
}

func (s *Service) listReadyStepIDs(ctx context.Context, limit int) ([]uuid.UUID, error) {
	return s.queries.ListReadyStepIDsForUpdateSkipLocked(ctx, int32(max(1, limit)))
}

func (s *Service) listRetryingStepIDsDue(ctx context.Context, limit int) ([]uuid.UUID, error) {
	return s.queries.ListRetryingStepIDsDueForUpdateSkipLocked(ctx, int32(max(1, limit)))
}

func (s *Service) dependenciesSatisfiedTx(ctx context.Context, tx pgx.Tx, dependencyIDs []uuid.UUID) (bool, error) {
	if len(dependencyIDs) == 0 {
		return true, nil
	}
	states, err := s.qtx(tx).GetDependencyStatesByIDs(ctx, dependencyIDs)
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

type stepRuntimeRequirements struct {
	requiresTrainedModel    bool
	primaryModelArtifactKey string
}

func defaultStepRuntimeRequirements(stepType db.Steptype) stepRuntimeRequirements {
	switch stepType {
	case db.SteptypeSCORE:
		return stepRuntimeRequirements{requiresTrainedModel: true, primaryModelArtifactKey: "best.pt"}
	case db.SteptypeEVAL:
		return stepRuntimeRequirements{requiresTrainedModel: true, primaryModelArtifactKey: "best.pt"}
	case db.SteptypeEXPORT:
		return stepRuntimeRequirements{requiresTrainedModel: true, primaryModelArtifactKey: "best.pt"}
	default:
		return stepRuntimeRequirements{requiresTrainedModel: false, primaryModelArtifactKey: ""}
	}
}

func (s *Service) resolvePreferredExecutorIDByDependenciesTx(
	ctx context.Context,
	tx pgx.Tx,
	dependencyIDs []uuid.UUID,
) (string, error) {
	if len(dependencyIDs) == 0 {
		return "", nil
	}
	executorID, err := s.qtx(tx).GetLatestAssignedExecutorByStepIDs(ctx, dependencyIDs)
	if err != nil {
		if err == pgx.ErrNoRows {
			return "", nil
		}
		return "", err
	}
	return strings.TrimSpace(executorID), nil
}

func (s *Service) pickExecutorWithRoundAffinity(
	pluginID string,
	preferredExecutorID string,
	readyAt *time.Time,
) (string, bool) {
	preferredExecutorID = strings.TrimSpace(preferredExecutorID)
	if preferredExecutorID == "" {
		executorID, found := s.dispatcher.PickExecutor(pluginID)
		if !found {
			return "", false
		}
		return executorID, false
	}

	if s.dispatcher.IsExecutorAvailable(preferredExecutorID, pluginID) {
		return preferredExecutorID, false
	}

	if s.roundAffinityWait > 0 && readyAt != nil {
		readySince := readyAt.UTC()
		elapsed := time.Since(readySince)
		if elapsed < 0 {
			elapsed = 0
		}
		if elapsed < s.roundAffinityWait {
			return "", true
		}
	}

	executorID, found := s.dispatcher.PickExecutor(pluginID)
	if !found {
		return "", false
	}
	return executorID, false
}

func (s *Service) buildDispatchResolvedParamsTx(
	ctx context.Context,
	tx pgx.Tx,
	stepPayload stepDispatchPayload,
) (*structpb.Struct, error) {
	requirements := defaultStepRuntimeRequirements(stepPayload.StepType)
	if !requirements.requiresTrainedModel {
		return stepPayload.Params, nil
	}
	artifactName := strings.TrimSpace(requirements.primaryModelArtifactKey)
	if artifactName == "" {
		artifactName = "best.pt"
	}

	if s.domainClient == nil {
		return nil, fmt.Errorf("runtime_domain 客户端未初始化")
	}
	if !s.domainClient.Configured() {
		return nil, runtime_domain_client.ErrNotConfigured
	}
	if !s.domainClient.Enabled() {
		return nil, runtime_domain_client.ErrDisabled
	}

	trainStepID, err := s.qtx(tx).GetLatestSucceededTrainStepIDByRound(ctx, stepPayload.RoundID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, fmt.Errorf(
				"round 缺少成功 TRAIN step，无法注入模型: round_id=%s step_id=%s",
				stepPayload.RoundID,
				stepPayload.StepID,
			)
		}
		return nil, err
	}

	downloadResp, err := s.domainClient.CreateDownloadTicket(ctx, &runtimedomainv1.DownloadTicketRequest{
		RequestId:    uuid.NewString(),
		StepId:       trainStepID.String(),
		ArtifactName: artifactName,
	})
	if err != nil {
		if runtime_domain_client.IsNotFoundError(err) {
			return nil, fmt.Errorf(
				"训练模型制品不存在: train_step_id=%s artifact=%s",
				trainStepID,
				artifactName,
			)
		}
		if runtime_domain_client.IsInvalidRequestError(err) {
			return nil, fmt.Errorf(
				"训练模型下载票据请求无效: train_step_id=%s artifact=%s",
				trainStepID,
				artifactName,
			)
		}
		return nil, fmt.Errorf(
			"训练模型下载票据请求失败: train_step_id=%s artifact=%s err=%w",
			trainStepID,
			artifactName,
			err,
		)
	}
	downloadURL := strings.TrimSpace(downloadResp.GetDownloadUrl())
	if downloadURL == "" {
		return nil, fmt.Errorf(
			"训练模型下载地址为空: train_step_id=%s artifact=%s",
			trainStepID,
			artifactName,
		)
	}

	paramsMap := cloneMap(structToMap(stepPayload.Params))
	pluginParams := ensureMap(paramsMap["plugin"])
	pluginParams["model_source"] = "custom_url"
	pluginParams["model_custom_ref"] = downloadURL
	paramsMap["plugin"] = pluginParams
	paramsMap["_runtime_model_handoff"] = map[string]any{
		"from_step_id":  trainStepID.String(),
		"artifact_name": artifactName,
		"download_url":  downloadURL,
		"injected_at":   time.Now().UTC().Format(time.RFC3339),
	}

	resolvedParams, err := structpb.NewStruct(paramsMap)
	if err != nil {
		return nil, err
	}
	return resolvedParams, nil
}

func (s *Service) failStepDispatchPreflightTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	reason string,
) error {
	affected, err := s.updateStepResultGuardedTx(
		ctx,
		tx,
		stepID,
		stepFailed,
		[]byte(`{}`),
		[]byte(`{}`),
		reason,
	)
	if err != nil {
		return err
	}
	if affected == 0 {
		return fmt.Errorf("预派发失败后状态更新冲突: step_id=%s", stepID)
	}
	return nil
}

func (s *Service) markStepDispatchingTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	executorID string,
	requestID string,
) (bool, error) {
	updated, err := s.qtx(tx).MarkStepDispatching(ctx, db.MarkStepDispatchingParams{
		AssignedExecutorID: toPGText(executorID),
		DispatchRequestID:  toPGText(requestID),
		StepID:             stepID,
	})
	if err != nil {
		return false, err
	}
	return updated > 0, nil
}

func (s *Service) promoteStepToReadyTx(ctx context.Context, tx pgx.Tx, stepID uuid.UUID) (bool, error) {
	updated, err := s.qtx(tx).PromoteStepToReady(ctx, stepID)
	if err != nil {
		return false, err
	}
	return updated > 0, nil
}

func (s *Service) promoteRetryingStepToReadyTx(ctx context.Context, tx pgx.Tx, stepID uuid.UUID) (bool, error) {
	updated, err := s.qtx(tx).PromoteRetryingStepToReady(ctx, stepID)
	if err != nil {
		return false, err
	}
	return updated > 0, nil
}

func (s *Service) findRoundIDByStep(ctx context.Context, tx pgx.Tx, stepID uuid.UUID) (*uuid.UUID, error) {
	roundID, err := s.qtx(tx).FindRoundIDByStep(ctx, stepID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	return &roundID, nil
}

func (s *Service) getStepPayloadByIDTx(ctx context.Context, tx pgx.Tx, stepID uuid.UUID) (stepDispatchPayload, bool, error) {
	record, err := s.qtx(tx).GetStepPayloadByIDForUpdate(ctx, stepID)
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

func (s *Service) insertStepEventTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	seq int64,
	ts time.Time,
	eventType string,
	payloadJSON string,
	requestID string,
) (bool, error) {
	affected, err := s.qtx(tx).InsertStepEvent(ctx, db.InsertStepEventParams{
		EventID:   uuid.New(),
		StepID:    stepID,
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
	stepID uuid.UUID,
	attempt int,
	reason string,
) (bool, error) {
	requestID := uuid.New()
	commandID := cancelAttemptCommandID(stepID, attempt)
	inserted, err := s.insertCommandLogTx(ctx, tx, requestID, commandID, "cancel_attempt", stepID.String())
	if err != nil {
		return false, err
	}
	if !inserted {
		return false, nil
	}

	stopRequestID, accepted := s.dispatcher.StopStep(stepID.String(), reason)
	detail := fmt.Sprintf("已发起取消尝试 accepted=%t stop_request_id=%s", accepted, strings.TrimSpace(stopRequestID))
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
	stepIDs []uuid.UUID,
	reason string,
) error {
	if len(stepIDs) == 0 {
		return nil
	}
	return s.qtx(tx).CancelStepsByIDs(ctx, db.CancelStepsByIDsParams{
		LastError: toPGText(reason),
		StepIds:   stepIDs,
	})
}

func (s *Service) loopHasActiveStepsTx(ctx context.Context, tx pgx.Tx, loopID uuid.UUID) (bool, error) {
	count, err := s.qtx(tx).CountLoopActiveSteps(ctx, loopID)
	if err != nil {
		return false, err
	}
	return count > 0, nil
}

func (s *Service) insertMetricPointsTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	step int,
	epoch *int,
	metrics map[string]float64,
	ts time.Time,
) error {
	if len(metrics) == 0 {
		return nil
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyStepMetricPointsParams, 0, len(metrics))
	for metricName, metricValue := range metrics {
		cleanMetricName := strings.TrimSpace(metricName)
		if cleanMetricName == "" {
			continue
		}
		rows = append(rows, db.CopyStepMetricPointsParams{
			ID:          uuid.New(),
			StepID:      stepID,
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
	stepID uuid.UUID,
	candidates []*runtimecontrolv1.QueryCandidate,
) error {
	if err := s.qtx(tx).DeleteStepCandidatesByStepID(ctx, stepID); err != nil {
		return err
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyStepCandidateItemsParams, 0, len(candidates))
	for idx, item := range candidates {
		sampleIDText := strings.TrimSpace(item.GetSampleId())
		if sampleIDText == "" {
			continue
		}
		parsedSampleID, err := parseUUID(sampleIDText)
		if err != nil {
			continue
		}
		reasonJSON, err := marshalJSON(structToMap(item.GetReason()))
		if err != nil {
			return err
		}
		rows = append(rows, db.CopyStepCandidateItemsParams{
			ID:                 uuid.New(),
			StepID:             stepID,
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
	stepID uuid.UUID,
	artifact *runtimecontrolv1.ArtifactItem,
) error {
	if artifact == nil {
		return nil
	}
	artifactName := strings.TrimSpace(artifact.GetName())
	if artifactName == "" {
		return nil
	}

	rawArtifacts, err := s.qtx(tx).GetStepArtifactsForUpdate(ctx, stepID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("未找到步骤: %s", stepID)
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
		StepID:    stepID,
	})
}

func (s *Service) dispatchOutboxBatch(ctx context.Context, limit int) (int, error) {
	if !s.dbEnabled() {
		return 0, nil
	}
	rows, err := s.queries.ClaimDispatchOutboxDue(ctx, int32(max(1, limit)))
	if err != nil {
		return 0, err
	}
	sent := 0
	for _, row := range rows {
		payload := &runtimecontrolv1.StepPayload{}
		if err := protojson.Unmarshal(row.Payload, payload); err != nil {
			nextAt := toPGTimestamp(time.Now().UTC().Add(dispatchOutboxRetryBackoff(row.AttemptCount)))
			_, retryErr := s.queries.MarkDispatchOutboxRetry(ctx, db.MarkDispatchOutboxRetryParams{
				NextAttemptAt: nextAt,
				LastError:     toNullablePGText(fmt.Sprintf("outbox 负载无效: %v", err)),
				OutboxID:      row.ID,
			})
			if retryErr != nil {
				return sent, retryErr
			}
			continue
		}

		if s.dispatcher.DispatchStep(row.ExecutorID, row.RequestID, payload) {
			affected, err := s.queries.MarkDispatchOutboxSent(ctx, row.ID)
			if err != nil {
				return sent, err
			}
			if affected > 0 {
				sent++
			}
			continue
		}

		nextAt := toPGTimestamp(time.Now().UTC().Add(dispatchOutboxRetryBackoff(row.AttemptCount)))
		_, err = s.queries.MarkDispatchOutboxRetry(ctx, db.MarkDispatchOutboxRetryParams{
			NextAttemptAt: nextAt,
			LastError:     toNullablePGText("executor 不可用或队列已满"),
			OutboxID:      row.ID,
		})
		if err != nil {
			return sent, err
		}
	}
	return sent, nil
}

func (s *Service) recoverDispatchOutbox(ctx context.Context, limit int) error {
	if !s.dbEnabled() {
		return nil
	}
	staleSendingCutoff := toPGTimestamp(time.Now().UTC().Add(-30 * time.Second))
	if _, err := s.queries.ReleaseStaleSendingOutbox(ctx, staleSendingCutoff); err != nil {
		return err
	}

	orphanCutoff := toPGTimestamp(time.Now().UTC().Add(-2 * time.Minute))
	stepIDs, err := s.queries.ListOrphanDispatchingStepIDs(ctx, db.ListOrphanDispatchingStepIDsParams{
		Cutoff:     orphanCutoff,
		LimitCount: int32(max(1, limit)),
	})
	if err != nil {
		return err
	}
	for _, stepID := range stepIDs {
		_, err = s.queries.RecoverStaleDispatchingStepToReady(ctx, db.RecoverStaleDispatchingStepToReadyParams{
			LastError: toPGText("已恢复孤儿派发记录"),
			StepID:    stepID,
		})
		if err != nil {
			return err
		}
	}

	cleanupCutoff := toPGTimestamp(time.Now().UTC().Add(-24 * time.Hour))
	if _, err := s.queries.DeleteSentDispatchOutboxBefore(ctx, cleanupCutoff); err != nil {
		return err
	}
	return nil
}

func dispatchOutboxRetryBackoff(attempt int32) time.Duration {
	if attempt <= 1 {
		return time.Second
	}
	seconds := 1 << minInt(6, int(attempt)-1)
	if seconds > 60 {
		seconds = 60
	}
	return time.Duration(seconds) * time.Second
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func (s *Service) OnExecutorRegister(ctx context.Context, register *runtimecontrolv1.Register) error {
	if !s.dbEnabled() || register == nil {
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

	return s.queries.UpsertRuntimeExecutorOnRegister(ctx, db.UpsertRuntimeExecutorOnRegisterParams{
		ExecutorRowID: uuid.New(),
		ExecutorID:    executorID,
		Version:       version,
		PluginIds:     []byte(pluginPayloadJSON),
		Resources:     []byte(resourcesJSON),
	})
}

func (s *Service) OnExecutorHeartbeat(ctx context.Context, heartbeat *runtimecontrolv1.Heartbeat) error {
	if !s.dbEnabled() || heartbeat == nil {
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
	currentStepUUID, err := parseNullableUUID(currentStepID)
	if err != nil {
		return err
	}
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(heartbeat.GetResources()))
	if err != nil {
		return err
	}

	return s.queries.UpsertRuntimeExecutorOnHeartbeat(ctx, db.UpsertRuntimeExecutorOnHeartbeatParams{
		ExecutorRowID: uuid.New(),
		ExecutorID:    executorID,
		Status:        status,
		CurrentStepID: currentStepUUID,
		Resources:     []byte(resourcesJSON),
	})
}

func (s *Service) OnExecutorDisconnected(ctx context.Context, executorID string, reason string) error {
	if !s.dbEnabled() {
		return nil
	}
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return nil
	}

	return s.queries.UpdateRuntimeExecutorDisconnected(ctx, db.UpdateRuntimeExecutorDisconnectedParams{
		Reason:     toNullablePGText(reason),
		ExecutorID: executorID,
	})
}
