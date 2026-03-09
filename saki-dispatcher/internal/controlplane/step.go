package controlplane

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/spf13/cast"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/structpb"

	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
	"github.com/elebirds/saki/saki-dispatcher/internal/runtime_domain_client"
)

var errSelectCandidatesNotReady = errors.New("select candidates not ready")

func isOrchestratorRetryableError(err error) bool {
	return runtime_domain_client.IsTransientError(err) || errors.Is(err, errSelectCandidatesNotReady)
}

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
	if err := s.recoverStaleInFlightTasks(ctx, max(64, limit*2)); err != nil {
		return 0, err
	}
	maintenanceMode, err := s.getRuntimeMaintenanceMode(ctx)
	if err != nil {
		return 0, err
	}
	if maintenanceMode != maintenanceModeNormal {
		return 0, nil
	}

	claimed := 0
	_ = s.dispatcher.DrainQueuedTaskIDs()
	candidateLimit := max(512, limit*32)
	for claimed < limit {
		candidates, err := s.listDispatchLaneCandidates(ctx, candidateLimit)
		if err != nil {
			return claimed, err
		}
		pass := s.selectDispatchPass(candidates, limit-claimed)
		if len(pass) == 0 {
			break
		}
		s.logger.Debug().
			Int("claimed", claimed).
			Int("limit", limit).
			Int("candidate_count", len(candidates)).
			Int("pass_count", len(pass)).
			Msg("dispatch_trace 候选轮次开始")
		dispatchedThisPass := 0
		for _, candidate := range pass {
			if _, available := s.dispatcher.PickExecutor(candidate.PluginID); !available {
				s.logger.Debug().
					Str("task_id", candidate.TaskID.String()).
					Str("lane_id", candidate.LaneID).
					Str("dispatch_class", candidate.DispatchClass).
					Str("plugin_id", candidate.PluginID).
					Msg("dispatch_trace 跳过：当前无可用 executor")
				continue
			}
			dispatched, err := s.dispatchTaskByID(ctx, candidate.TaskID)
			if err != nil {
				return claimed, err
			}
			if dispatched {
				claimed++
				dispatchedThisPass++
				s.recordLaneDispatch(candidate.LaneID)
				continue
			}
			if candidate.IsReady {
				if _, stillAvailable := s.dispatcher.PickExecutor(candidate.PluginID); stillAvailable {
					s.incrementLaneSkip(candidate.LaneID)
					s.logger.Debug().
						Str("task_id", candidate.TaskID.String()).
						Str("lane_id", candidate.LaneID).
						Str("dispatch_class", candidate.DispatchClass).
						Msg("dispatch_trace 未派发：lane 增加 aging")
				}
			}
		}
		if dispatchedThisPass == 0 {
			break
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

func (s *Service) dispatchStepTaskByID(ctx context.Context, taskID uuid.UUID) (bool, error) {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	stepPayload, ok, err := s.getStepPayloadByIDTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !ok {
		return false, tx.Commit(ctx)
	}

	taskStatus := normalizeTaskEnumText(string(stepPayload.TaskStatus))
	if taskStatus == "PENDING" || taskStatus == "RETRYING" {
		loopLifecycle, err := s.qtx(tx).GetLoopLifecycle(ctx, stepPayload.LoopID)
		if err != nil {
			if err == pgx.ErrNoRows {
				return false, tx.Commit(ctx)
			}
			return false, err
		}
		if loopLifecycle != db.LooplifecycleRUNNING {
			return false, tx.Commit(ctx)
		}
		depsOK, err := s.dependenciesSatisfiedTx(ctx, tx, stepPayload.DependsOnTaskIDs)
		if err != nil {
			return false, err
		}
		if !depsOK {
			return false, tx.Commit(ctx)
		}
		promoteToReady := s.promoteTaskToReadyTx
		if taskStatus == "RETRYING" {
			if !isRetryDue(time.Now().UTC(), stepPayload.UpdatedAt, stepPayload.Attempt) {
				return false, tx.Commit(ctx)
			}
			promoteToReady = s.promoteRetryingTaskToReadyTx
		}
		promoted, err := promoteToReady(ctx, tx, taskID)
		if err != nil {
			return false, err
		}
		if !promoted {
			return false, tx.Commit(ctx)
		}
		stepPayload.TaskStatus = db.RuntimetaskstatusREADY
		taskStatus = "READY"
		now := time.Now().UTC()
		stepPayload.UpdatedAt = &now
	}

	if taskStatus != "READY" {
		return false, tx.Commit(ctx)
	}
	if err := s.syncLoopPhaseWithStepTx(ctx, tx, stepPayload); err != nil {
		return false, err
	}
	if isOrchestratorDispatchKind(stepPayload.DispatchKind) {
		executed, err := s.executeOrchestratorStepTx(ctx, tx, taskID, stepPayload)
		if err != nil {
			return false, err
		}
		return executed, tx.Commit(ctx)
	}

	loopPreferredExecutorID := preferredExecutorIDFromResolvedParams(stepPayload.Params)
	dependencyPreferredExecutorID := ""
	if loopPreferredExecutorID == "" {
		preferredExecutorID, resolveErr := s.resolvePreferredExecutorIDByDependenciesTx(
			ctx,
			tx,
			stepPayload.DependsOnTaskIDs,
		)
		if resolveErr != nil {
			return false, resolveErr
		}
		dependencyPreferredExecutorID = preferredExecutorID
	}
	executorID, deferredByAffinity, blockedByLoopBinding := s.pickExecutorForStepDispatch(
		stepPayload.PluginID,
		stepPayload.UpdatedAt,
		dependencyPreferredExecutorID,
		loopPreferredExecutorID,
	)
	_ = blockedByLoopBinding
	readyAge := time.Duration(0)
	if stepPayload.UpdatedAt != nil {
		readyAge = time.Since(stepPayload.UpdatedAt.UTC())
		if readyAge < 0 {
			readyAge = 0
		}
	}
	if deferredByAffinity {
		s.logger.Debug().
			Str("task_id", taskID.String()).
			Str("step_id", stepPayload.StepID.String()).
			Str("step_type", strings.ToLower(string(stepPayload.StepType))).
			Str("plugin_id", stepPayload.PluginID).
			Str("loop_preferred_executor_id", loopPreferredExecutorID).
			Str("dependency_preferred_executor_id", dependencyPreferredExecutorID).
			Dur("ready_age", readyAge).
			Msg("dispatch_trace 等待 affinity 窗口")
		return false, tx.Commit(ctx)
	}
	if strings.TrimSpace(executorID) == "" {
		s.logger.Debug().
			Str("task_id", taskID.String()).
			Str("step_id", stepPayload.StepID.String()).
			Str("step_type", strings.ToLower(string(stepPayload.StepType))).
			Str("plugin_id", stepPayload.PluginID).
			Str("loop_preferred_executor_id", loopPreferredExecutorID).
			Str("dependency_preferred_executor_id", dependencyPreferredExecutorID).
			Dur("ready_age", readyAge).
			Msg("dispatch_trace 等待可用 executor")
		return false, tx.Commit(ctx)
	}

	resolvedParams, err := s.buildDispatchResolvedParamsTx(ctx, tx, stepPayload)
	if err != nil {
		if !s.strictModelHandoff {
			s.logger.Warn().
				Err(err).
				Str("task_id", taskID.String()).
				Str("step_id", stepPayload.StepID.String()).
				Str("task_type", strings.ToLower(string(stepPayload.StepType))).
				Msg("训练模型交接失败，STRICT_TRAIN_MODEL_HANDOFF=false，回退旧行为")
			resolvedParams = stepPayload.Params
		} else {
			reason := strings.TrimSpace(err.Error())
			if reason == "" {
				reason = "训练模型交接失败"
			}
			if failErr := s.failTaskDispatchPreflightTx(ctx, tx, taskID, reason); failErr != nil {
				return false, failErr
			}
			if _, refreshErr := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); refreshErr != nil {
				return false, refreshErr
			}
			s.logger.Warn().
				Str("task_id", taskID.String()).
				Str("step_id", stepPayload.StepID.String()).
				Str("task_type", strings.ToLower(string(stepPayload.StepType))).
				Msgf("训练模型交接失败，步骤已标记 FAILED: %s", reason)
			return true, tx.Commit(ctx)
		}
	}

	requestID := uuid.NewString()
	updated, err := s.markTaskDispatchingTx(ctx, tx, taskID, executorID, requestID)
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
	message := &runtimecontrolv1.TaskPayload{
		TaskId:           taskID.String(),
		RoundId:          stepPayload.RoundID.String(),
		LoopId:           stepPayload.LoopID.String(),
		ProjectId:        stepPayload.ProjectID.String(),
		InputCommitId:    inputCommitID,
		TaskType:         toRuntimeTaskType(stepPayload.StepType),
		DispatchKind:     toRuntimeTaskDispatchKind(stepPayload.DispatchKind),
		PluginId:         stepPayload.PluginID,
		Mode:             toRuntimeLoopMode(stepPayload.Mode),
		QueryStrategy:    resolveTaskPayloadQueryStrategy(string(stepPayload.StepType), resolvedParams),
		ResolvedParams:   resolvedParams,
		Resources:        stepPayload.Resources,
		RoundIndex:       int32(stepPayload.RoundIndex),
		Attempt:          int32(stepPayload.Attempt),
		DependsOnTaskIds: stringifyUUIDs(stepPayload.DependsOnTaskIDs),
		ExecutionId:      stepPayload.CurrentExecutionID.String(),
	}
	payloadRaw, err := protojson.Marshal(message)
	if err != nil {
		return false, err
	}
	outboxID := uuid.New()
	inserted, err := s.qtx(tx).InsertDispatchOutbox(ctx, db.InsertDispatchOutboxParams{
		OutboxID:   outboxID,
		TaskID:     taskID,
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
	s.logger.Info().
		Str("task_id", taskID.String()).
		Str("step_id", stepPayload.StepID.String()).
		Str("round_id", stepPayload.RoundID.String()).
		Str("loop_id", stepPayload.LoopID.String()).
		Str("step_type", strings.ToLower(string(stepPayload.StepType))).
		Str("plugin_id", stepPayload.PluginID).
		Str("executor_id", executorID).
		Str("request_id", requestID).
		Str("execution_id", stepPayload.CurrentExecutionID.String()).
		Str("loop_preferred_executor_id", loopPreferredExecutorID).
		Str("dependency_preferred_executor_id", dependencyPreferredExecutorID).
		Msg("dispatch_trace step 已写入调度 outbox")
	return true, tx.Commit(ctx)
}

func (s *Service) dispatchTaskByID(ctx context.Context, taskID uuid.UUID) (bool, error) {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	taskRow, found, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, tx.Commit(ctx)
	}
	taskKind := normalizeTaskEnumText(taskRow.Kind)
	if taskKind == "PREDICTION" {
		if err := tx.Commit(ctx); err != nil {
			return false, err
		}
		return s.dispatchPredictionTaskByID(ctx, taskID)
	}
	if taskKind != "STEP" {
		return false, tx.Commit(ctx)
	}

	_, mapped, err := s.resolveStepIDForTaskTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !mapped {
		reason := "step projection missing"
		if err := s.updateTaskStatusTx(ctx, tx, taskID, "FAILED", reason); err != nil {
			return false, err
		}
		s.logger.Warn().
			Str("task_id", taskID.String()).
			Str("task_kind", taskKind).
			Msg("检测到无 step 投影的 step task，已标记 FAILED")
		return true, tx.Commit(ctx)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, err
	}
	return s.dispatchStepTaskByID(ctx, taskID)
}

func (s *Service) dispatchPredictionTaskByID(ctx context.Context, taskID uuid.UUID) (bool, error) {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	taskRow, found, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, tx.Commit(ctx)
	}
	if normalizeTaskEnumText(taskRow.Kind) != "PREDICTION" {
		return false, tx.Commit(ctx)
	}
	if isTerminalTaskStatus(taskRow.Status) {
		return false, tx.Commit(ctx)
	}
	if !isTaskStatusDispatchable(taskRow.Status) {
		return false, tx.Commit(ctx)
	}

	executorID, ok := s.dispatcher.PickExecutor(strings.TrimSpace(taskRow.PluginID))
	if !ok || strings.TrimSpace(executorID) == "" {
		s.logger.Debug().
			Str("task_id", taskID.String()).
			Str("plugin_id", strings.TrimSpace(taskRow.PluginID)).
			Msg("dispatch_trace prediction 等待可用 executor")
		return false, tx.Commit(ctx)
	}

	resolvedParams, err := toStruct(taskRow.ResolvedParamsJSON)
	if err != nil {
		return false, err
	}
	attempt := max(1, taskRow.Attempt)
	inputCommitID := ""
	if taskRow.InputCommitID != nil {
		inputCommitID = taskRow.InputCommitID.String()
	}

	requestID := uuid.NewString()
	affected, err := s.qtx(tx).MarkTaskDispatching(ctx, db.MarkTaskDispatchingParams{
		AssignedExecutorID: toPGText(executorID),
		TaskID:             taskRow.ID,
	})
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, tx.Commit(ctx)
	}

	payload := &runtimecontrolv1.TaskPayload{
		TaskId:           taskRow.ID.String(),
		RoundId:          "",
		LoopId:           "",
		ProjectId:        taskRow.ProjectID.String(),
		InputCommitId:    inputCommitID,
		TaskType:         runtimeTaskTypeFromTaskType(taskRow.TaskType),
		DispatchKind:     runtimecontrolv1.RuntimeTaskDispatchKind_DISPATCHABLE,
		PluginId:         strings.TrimSpace(taskRow.PluginID),
		Mode:             runtimecontrolv1.RuntimeLoopMode_MANUAL,
		QueryStrategy:    resolveTaskPayloadQueryStrategy(taskRow.TaskType, resolvedParams),
		ResolvedParams:   resolvedParams,
		Resources:        &runtimecontrolv1.ResourceSummary{},
		RoundIndex:       0,
		Attempt:          int32(attempt),
		DependsOnTaskIds: []string{},
		ExecutionId:      taskRow.CurrentExecutionID.String(),
	}
	if !s.dispatcher.DispatchTask(executorID, requestID, payload) {
		_, _ = s.qtx(tx).ResetTaskToReadyQueueFull(ctx, taskRow.ID)
		s.logger.Warn().
			Str("task_id", taskRow.ID.String()).
			Str("plugin_id", strings.TrimSpace(taskRow.PluginID)).
			Str("executor_id", executorID).
			Str("request_id", requestID).
			Msg("dispatch_trace prediction 派发失败：dispatcher 队列已满，已回退 READY")
		return false, tx.Commit(ctx)
	}
	s.logger.Info().
		Str("task_id", taskRow.ID.String()).
		Str("plugin_id", strings.TrimSpace(taskRow.PluginID)).
		Str("executor_id", executorID).
		Str("request_id", requestID).
		Str("execution_id", taskRow.CurrentExecutionID.String()).
		Msg("dispatch_trace prediction 已派发到 executor")
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

func resolveTaskPayloadQueryStrategy(taskType string, resolvedParams *structpb.Struct) string {
	if strings.EqualFold(strings.TrimSpace(taskType), "predict") {
		return ""
	}
	return extractSamplingStrategyFromStruct(resolvedParams)
}

func (s *Service) executeOrchestratorStepTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	stepPayload stepDispatchPayload,
) (bool, error) {
	started, err := s.qtx(tx).MarkOrchestratorTaskRunning(ctx, taskID)
	if err != nil {
		return false, err
	}
	if started == 0 {
		return false, nil
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return false, err
	}

	resultTaskStatus := db.RuntimetaskstatusSUCCEEDED
	lastError := ""
	if err := s.runOrchestratorStepTx(ctx, tx, stepPayload); err != nil {
		lastError = strings.TrimSpace(err.Error())
		if lastError == "" {
			lastError = "编排步骤执行失败"
		}
		if isOrchestratorRetryableError(err) {
			retried, retryErr := s.markOrchestratorTaskRetryingTx(ctx, tx, taskID, lastError)
			if retryErr != nil {
				return false, retryErr
			}
			if retried {
				if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
					return false, err
				}
				if _, refreshErr := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); refreshErr != nil {
					return false, refreshErr
				}
				return true, nil
			}
			lastError = fmt.Sprintf("临时错误且超过最大重试次数: %s", lastError)
		}
		resultTaskStatus = db.RuntimetaskstatusFAILED
	}

	affected, err := s.qtx(tx).UpdateTaskExecutionResultGuarded(ctx, db.UpdateTaskExecutionResultGuardedParams{
		Status:     resultTaskStatus,
		LastError:  toNullablePGText(lastError),
		TaskID:     taskID,
		FromStatus: db.RuntimetaskstatusRUNNING,
	})
	if err != nil {
		return false, err
	}
	if affected == 0 {
		return false, nil
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return false, err
	}

	if _, err := s.refreshRoundAggregateTx(ctx, tx, stepPayload.RoundID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) markOrchestratorTaskRetryingTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	reason string,
) (bool, error) {
	affected, err := s.qtx(tx).MarkOrchestratorTaskRetrying(ctx, db.MarkOrchestratorTaskRetryingParams{
		LastError: toPGText(reason),
		TaskID:    taskID,
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
) error {
	switch stepPayload.StepType {
	case db.SteptypeSELECT:
		return s.runSelectTopKTx(ctx, tx, stepPayload)
	default:
		return fmt.Errorf("unsupported orchestrator step type: %s", stepPayload.StepType)
	}
}

func (s *Service) runSelectTopKTx(ctx context.Context, tx pgx.Tx, stepPayload stepDispatchPayload) error {
	selectTaskID := stepPayload.StepID
	if stepPayload.TaskID != nil {
		selectTaskID = *stepPayload.TaskID
	} else if mappedTaskID, ok, mapErr := s.resolveTaskIDForStepTx(ctx, tx, stepPayload.StepID); mapErr != nil {
		return mapErr
	} else if ok {
		selectTaskID = mappedTaskID
	}

	queryBatchRaw, err := s.qtx(tx).GetLoopQueryBatchSize(ctx, stepPayload.LoopID)
	if err != nil {
		return err
	}
	queryBatch := int(queryBatchRaw)
	if queryBatch <= 0 {
		queryBatch = 1
	}

	scoreTaskID, err := s.qtx(tx).GetSucceededScoreTaskIDByRound(ctx, stepPayload.RoundID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return fmt.Errorf("%w: score task not ready task_id=%s step_id=%s round_id=%s", errSelectCandidatesNotReady, selectTaskID, stepPayload.StepID, stepPayload.RoundID)
		}
		return err
	}
	rows, err := s.qtx(tx).ListTaskCandidatesByTaskID(ctx, db.ListTaskCandidatesByTaskIDParams{
		TaskID:     scoreTaskID,
		LimitCount: int32(queryBatch),
	})
	if err != nil {
		return err
	}
	if len(rows) == 0 {
		return fmt.Errorf("%w: score_task_id=%s round_id=%s", errSelectCandidatesNotReady, scoreTaskID, stepPayload.RoundID)
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
	if err := s.qtx(tx).DeleteTaskCandidatesByTaskID(ctx, selectTaskID); err != nil {
		return err
	}
	copyRows := make([]db.CopyTaskCandidateItemsParams, 0, len(candidates))
	now := toPGTimestamp(time.Now().UTC())
	for idx, item := range candidates {
		copyRows = append(copyRows, db.CopyTaskCandidateItemsParams{
			ID:                 uuid.New(),
			TaskID:             selectTaskID,
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
		if _, err := s.qtx(tx).CopyTaskCandidateItems(ctx, copyRows); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) OnTaskEvent(ctx context.Context, event *runtimecontrolv1.TaskEvent) error {
	if !s.dbEnabled() || event == nil {
		return nil
	}
	taskID, err := parseUUID(event.GetTaskId())
	if err != nil {
		return nil
	}
	executionID, ok := parseExecutionID(event.GetExecutionId())
	if !ok {
		s.logger.Warn().
			Str("task_id", taskID.String()).
			Msg("task_event 缺少 execution_id，已忽略")
		return nil
	}

	eventType, eventPayload, statusValue := decodeTaskEvent(event)
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

	taskRow, foundTask, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if !foundTask {
		return tx.Commit(ctx)
	}
	if taskRow.CurrentExecutionID != executionID {
		s.logStaleExecutionMessage("task_event", taskID, executionID, taskRow.CurrentExecutionID)
		return tx.Commit(ctx)
	}

	stepID, found, err := s.resolveStepIDForTaskTx(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if inserted, err := s.insertTaskEventTx(
		ctx,
		tx,
		taskID,
		event.GetSeq(),
		eventTS,
		eventType,
		payloadJSON,
		strings.TrimSpace(event.GetRequestId()),
		executionID,
	); err != nil {
		return err
	} else if !inserted {
		// Duplicate event by (task_id, execution_id, seq), skip side effects.
		return tx.Commit(ctx)
	}
	statusReason := strings.TrimSpace(event.GetStatusEvent().GetReason())
	if eventType == "status" {
		targetTaskStatus := normalizeTaskEnumText(string(statusValue))
		if targetTaskStatus != "" && targetTaskStatus != "PENDING" {
			applied, err := s.applyRuntimeTaskStatusEventTx(ctx, tx, taskRow, targetTaskStatus, statusReason)
			if err != nil {
				return err
			}
			if applied && found && shouldApplyRuntimeTaskStatus(statusValue) {
				if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
					return err
				}
			}
		}
	}
	if !found {
		return tx.Commit(ctx)
	}

	switch eventType {
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
			if err := s.mergeArtifactIntoStepTx(ctx, tx, stepID, artifactPayload.GetArtifact()); err != nil {
				s.logger.Warn().
					Err(err).
					Str("task_id", taskID.String()).
					Str("step_id", stepID.String()).
					Msg("任务制品事件写入 step 投影失败，已保留 task 主干状态")
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

func (s *Service) OnTaskResult(ctx context.Context, result *runtimecontrolv1.TaskResult) error {
	if !s.dbEnabled() || result == nil {
		return nil
	}
	taskID, err := parseUUID(result.GetTaskId())
	if err != nil {
		return nil
	}
	executionID, ok := parseExecutionID(result.GetExecutionId())
	if !ok {
		s.logger.Warn().
			Str("task_id", taskID.String()).
			Msg("task_result 缺少 execution_id，已忽略")
		return nil
	}
	targetTaskStatus, ok := runtimeStatusToTaskStatus(result.GetStatus())
	if !ok {
		targetTaskStatus = taskFailed
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

	taskRow, foundTask, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if !foundTask {
		return tx.Commit(ctx)
	}
	if taskRow.CurrentExecutionID != executionID {
		s.logStaleExecutionMessage("task_result", taskID, executionID, taskRow.CurrentExecutionID)
		return tx.Commit(ctx)
	}

	stepID, found, err := s.resolveStepIDForTaskTx(ctx, tx, taskID)
	if err != nil {
		return err
	}
	applied, err := s.persistTaskResultTx(
		ctx,
		tx,
		taskID,
		executionID,
		targetTaskStatus,
		result.GetMetrics(),
		result.GetArtifacts(),
		result.GetCandidates(),
		strings.TrimSpace(result.GetErrorMessage()),
		result.GetWarnings(),
	)
	if err != nil {
		return err
	}
	if !applied {
		return tx.Commit(ctx)
	}
	if !found {
		return tx.Commit(ctx)
	}

	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return err
	}
	affected, err := s.qtx(tx).UpdateStepResultProjection(ctx, db.UpdateStepResultProjectionParams{
		Metrics:   []byte(metricsJSON),
		Artifacts: []byte(artifactsJSON),
		StepID:    stepID,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		s.logger.Warn().
			Str("task_id", taskID.String()).
			Str("step_id", stepID.String()).
			Str("target_status", string(targetTaskStatus)).
			Msg("任务结果的步骤内容投影冲突，已保留 task 主干结果")
		return tx.Commit(ctx)
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

func runtimeTaskStatusFromText(raw string) (db.Runtimetaskstatus, bool) {
	switch normalizeTaskEnumText(raw) {
	case "PENDING":
		return db.RuntimetaskstatusPENDING, true
	case "READY":
		return db.RuntimetaskstatusREADY, true
	case "DISPATCHING":
		return db.RuntimetaskstatusDISPATCHING, true
	case "SYNCING_ENV":
		return db.RuntimetaskstatusSYNCINGENV, true
	case "PROBING_RUNTIME":
		return db.RuntimetaskstatusPROBINGRUNTIME, true
	case "BINDING_DEVICE":
		return db.RuntimetaskstatusBINDINGDEVICE, true
	case "RUNNING":
		return db.RuntimetaskstatusRUNNING, true
	case "RETRYING":
		return db.RuntimetaskstatusRETRYING, true
	case "SUCCEEDED":
		return db.RuntimetaskstatusSUCCEEDED, true
	case "FAILED":
		return db.RuntimetaskstatusFAILED, true
	case "CANCELLED":
		return db.RuntimetaskstatusCANCELLED, true
	case "SKIPPED":
		return db.RuntimetaskstatusSKIPPED, true
	default:
		return "", false
	}
}

func (s *Service) updateTaskStatusTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	targetStatus string,
	reason string,
) error {
	targetStatus = normalizeTaskEnumText(targetStatus)
	if targetStatus == "" {
		return nil
	}
	reason = strings.TrimSpace(reason)
	taskStatus, ok := runtimeTaskStatusFromText(targetStatus)
	if !ok {
		return nil
	}
	lastError := toNullablePGText("")
	if targetStatus == "FAILED" || targetStatus == "CANCELLED" || targetStatus == "SKIPPED" || targetStatus == "RETRYING" {
		lastError = toNullablePGText(reason)
	}
	_, err := s.qtx(tx).UpdateTaskStatusLifecycle(ctx, db.UpdateTaskStatusLifecycleParams{
		Status:    taskStatus,
		LastError: lastError,
		TaskID:    taskID,
	})
	if err != nil {
		return err
	}
	return nil
}

func (s *Service) applyRuntimeTaskStatusEventTx(
	ctx context.Context,
	tx pgx.Tx,
	taskRow runtimeTaskRow,
	targetStatus string,
	reason string,
) (bool, error) {
	currentStatus, ok := runtimeTaskStatusFromText(taskRow.Status)
	if !ok {
		return false, nil
	}
	targetTaskStatus, ok := runtimeTaskStatusFromText(targetStatus)
	if !ok {
		return false, nil
	}
	if !canApplyTaskStatusTransition(currentStatus, targetTaskStatus) {
		return false, nil
	}
	if err := s.updateTaskStatusTx(ctx, tx, taskRow.ID, targetStatus, reason); err != nil {
		return false, err
	}
	return true, nil
}

func shouldApplyRuntimeTaskStatus(target db.Runtimetaskstatus) bool {
	return normalizeTaskEnumText(string(target)) != "" && target != taskPending
}

func parseExecutionID(raw string) (uuid.UUID, bool) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return uuid.Nil, false
	}
	parsed, err := uuid.Parse(value)
	if err != nil {
		return uuid.Nil, false
	}
	return parsed, true
}

func normalizeWarningList(warnings []string) []string {
	if len(warnings) == 0 {
		return []string{}
	}
	items := make([]string, 0, len(warnings))
	for _, item := range warnings {
		text := strings.TrimSpace(item)
		if text == "" {
			continue
		}
		items = append(items, text)
	}
	return items
}

func (s *Service) logStaleExecutionMessage(
	messageType string,
	taskID uuid.UUID,
	received uuid.UUID,
	current uuid.UUID,
) {
	s.logger.Warn().
		Str("message_type", strings.TrimSpace(messageType)).
		Str("task_id", taskID.String()).
		Str("received_execution_id", received.String()).
		Str("current_execution_id", current.String()).
		Msg("已丢弃过期 execution 消息")
}

func buildTaskResultCandidateRows(candidates []*runtimecontrolv1.QueryCandidate) []map[string]any {
	rows := make([]map[string]any, 0, len(candidates))
	for idx, item := range candidates {
		sampleID := strings.TrimSpace(item.GetSampleId())
		if sampleID == "" {
			continue
		}
		reasonPayload := structToMap(item.GetReason())
		snapshot := extractPredictionSnapshotFromReason(reasonPayload)
		rows = append(rows, map[string]any{
			"sample_id":           sampleID,
			"rank":                idx + 1,
			"score":               item.GetScore(),
			"reason":              reasonPayload,
			"prediction_snapshot": snapshot,
		})
	}
	return rows
}

func (s *Service) persistTaskResultTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	executionID uuid.UUID,
	targetTaskStatus db.Runtimetaskstatus,
	metrics map[string]float64,
	artifacts []*runtimecontrolv1.ArtifactItem,
	candidates []*runtimecontrolv1.QueryCandidate,
	errorMessage string,
	warnings []string,
) (bool, error) {
	taskRow, found, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return false, err
	}
	if !found {
		return false, nil
	}
	if taskRow.CurrentExecutionID != executionID {
		s.logStaleExecutionMessage("task_result", taskID, executionID, taskRow.CurrentExecutionID)
		return false, nil
	}
	currentStatus, ok := runtimeTaskStatusFromText(taskRow.Status)
	if !ok {
		return false, nil
	}
	if !canApplyTaskStatusTransition(currentStatus, targetTaskStatus) {
		return false, nil
	}
	paramsMap, err := parseJSONObject(taskRow.ResolvedParamsJSON)
	if err != nil {
		return false, err
	}
	paramsMap["_result_metrics"] = metrics
	artifactJSON, err := marshalArtifacts(artifacts)
	if err != nil {
		return false, err
	}
	artifactPayload, err := parseJSONObject([]byte(artifactJSON))
	if err != nil {
		return false, err
	}
	paramsMap["_result_artifacts"] = artifactPayload
	if err := s.replaceTaskCandidatesTx(ctx, tx, taskID, candidates); err != nil {
		return false, err
	}
	delete(paramsMap, "_result_candidates")
	errorMessage = strings.TrimSpace(errorMessage)
	if errorMessage == "" {
		delete(paramsMap, "_result_error_message")
	} else {
		paramsMap["_result_error_message"] = errorMessage
	}
	paramsMap["_result_completed_at"] = time.Now().UTC().Format(time.RFC3339)
	resolvedParamsJSON, err := marshalJSON(paramsMap)
	if err != nil {
		return false, err
	}
	if normalizeTaskEnumText(string(targetTaskStatus)) == "" {
		targetTaskStatus = db.RuntimetaskstatusFAILED
	}
	warningsJSON, err := marshalJSON(normalizeWarningList(warnings))
	if err != nil {
		return false, err
	}
	lastError := toNullablePGText("")
	if targetTaskStatus == db.RuntimetaskstatusFAILED ||
		targetTaskStatus == db.RuntimetaskstatusCANCELLED ||
		targetTaskStatus == db.RuntimetaskstatusSKIPPED {
		lastError = toNullablePGText(errorMessage)
	}
	_, err = s.qtx(tx).UpdateTaskResult(ctx, db.UpdateTaskResultParams{
		Status:         targetTaskStatus,
		ResolvedParams: []byte(resolvedParamsJSON),
		Warnings:       []byte(warningsJSON),
		LastError:      lastError,
		TaskID:         taskID,
	})
	if err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) listReadyTaskIDs(ctx context.Context, limit int) ([]uuid.UUID, error) {
	return s.queries.ListReadyTaskIDsForDispatch(ctx, int32(max(1, limit)))
}

func isTaskStatusDispatchable(status string) bool {
	switch normalizeTaskEnumText(status) {
	case "PENDING", "READY", "RETRYING":
		return true
	default:
		return false
	}
}

func runtimeTaskTypeFromTaskType(taskType string) runtimecontrolv1.RuntimeTaskType {
	switch normalizeTaskEnumText(taskType) {
	case "TRAIN":
		return runtimecontrolv1.RuntimeTaskType_TRAIN
	case "EVAL":
		return runtimecontrolv1.RuntimeTaskType_EVAL
	case "SCORE":
		return runtimecontrolv1.RuntimeTaskType_SCORE
	case "SELECT":
		return runtimecontrolv1.RuntimeTaskType_SELECT
	case "PREDICT":
		return runtimecontrolv1.RuntimeTaskType_PREDICT
	case "CUSTOM":
		return runtimecontrolv1.RuntimeTaskType_CUSTOM
	default:
		return runtimecontrolv1.RuntimeTaskType_RUNTIME_TASK_TYPE_UNSPECIFIED
	}
}

func runtimeLoopModeFromText(raw string) runtimecontrolv1.RuntimeLoopMode {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "active_learning":
		return runtimecontrolv1.RuntimeLoopMode_ACTIVE_LEARNING
	case "simulation":
		return runtimecontrolv1.RuntimeLoopMode_SIMULATION
	case "manual":
		return runtimecontrolv1.RuntimeLoopMode_MANUAL
	default:
		return runtimecontrolv1.RuntimeLoopMode_RUNTIME_LOOP_MODE_UNSPECIFIED
	}
}

func toIntValue(raw any, fallback int) int {
	switch value := raw.(type) {
	case int:
		return value
	case int32:
		return int(value)
	case int64:
		return int(value)
	case float32:
		return int(value)
	case float64:
		return int(value)
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(value))
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func retryBackoffDelay(attempt int) time.Duration {
	switch {
	case attempt <= 1:
		return time.Second
	case attempt == 2:
		return 2 * time.Second
	case attempt == 3:
		return 4 * time.Second
	case attempt == 4:
		return 8 * time.Second
	case attempt == 5:
		return 16 * time.Second
	default:
		return 30 * time.Second
	}
}

func isRetryDue(now time.Time, updatedAt *time.Time, attempt int) bool {
	if updatedAt == nil {
		return true
	}
	dueAt := updatedAt.UTC().Add(retryBackoffDelay(attempt))
	return !now.Before(dueAt)
}

func stringifyUUIDs(values []uuid.UUID) []string {
	if len(values) == 0 {
		return nil
	}
	items := make([]string, 0, len(values))
	for _, value := range values {
		items = append(items, value.String())
	}
	return items
}

func (s *Service) dependenciesSatisfiedTx(ctx context.Context, tx pgx.Tx, dependencyIDs []uuid.UUID) (bool, error) {
	if len(dependencyIDs) == 0 {
		return true, nil
	}
	rows, err := s.qtx(tx).GetDependencyTaskStatusesByIDs(ctx, dependencyIDs)
	if err != nil {
		return false, err
	}
	return dependencyRowsReady(rows, len(dependencyIDs)), nil
}

func dependencyRowsReady(rows []db.GetDependencyTaskStatusesByIDsRow, expectedCount int) bool {
	if len(rows) != expectedCount {
		return false
	}
	for _, row := range rows {
		if row.Status != db.RuntimetaskstatusSUCCEEDED {
			return false
		}
		if !row.ResultReadyAt.Valid {
			return false
		}
	}
	return true
}

type stepRuntimeRequirements struct {
	requiresTrainedModel    bool
	primaryModelArtifactKey string
	fallbackArtifactKeys    []string
}

func defaultStepRuntimeRequirements(stepType db.Steptype) stepRuntimeRequirements {
	switch stepType {
	case db.SteptypeSCORE:
		return stepRuntimeRequirements{
			requiresTrainedModel:    true,
			primaryModelArtifactKey: "best.pt",
			// 兼容不同训练插件产物命名（YOLO 常见 best.pt，MM 系常见 best.pth）。
			fallbackArtifactKeys: []string{"best.pth"},
		}
	case db.SteptypeEVAL:
		return stepRuntimeRequirements{
			requiresTrainedModel:    true,
			primaryModelArtifactKey: "best.pt",
			fallbackArtifactKeys:    []string{"best.pth"},
		}
	default:
		return stepRuntimeRequirements{requiresTrainedModel: false, primaryModelArtifactKey: ""}
	}
}

func resolveModelArtifactCandidates(requirements stepRuntimeRequirements) []string {
	seen := make(map[string]struct{})
	ordered := make([]string, 0, 4)
	appendKey := func(key string) {
		normalized := strings.TrimSpace(key)
		if normalized == "" {
			return
		}
		if _, exists := seen[normalized]; exists {
			return
		}
		seen[normalized] = struct{}{}
		ordered = append(ordered, normalized)
	}

	appendKey(requirements.primaryModelArtifactKey)
	for _, key := range requirements.fallbackArtifactKeys {
		appendKey(key)
	}
	// 保底值，避免调用方遗漏 primary 时候选为空。
	if len(ordered) == 0 {
		appendKey("best.pt")
		appendKey("best.pth")
	}
	return ordered
}

func (s *Service) resolvePreferredExecutorIDByDependenciesTx(
	ctx context.Context,
	tx pgx.Tx,
	dependencyIDs []uuid.UUID,
) (string, error) {
	if len(dependencyIDs) == 0 {
		return "", nil
	}
	executorID, err := s.qtx(tx).GetLatestAssignedExecutorByTaskIDs(ctx, dependencyIDs)
	if err != nil {
		if err == pgx.ErrNoRows {
			return "", nil
		}
		return "", err
	}
	return strings.TrimSpace(executorID), nil
}

func preferredExecutorIDFromResolvedParams(params *structpb.Struct) string {
	payload := structToMap(params)
	executionRaw, ok := payload["execution"]
	if !ok {
		return ""
	}
	executionMap, ok := executionRaw.(map[string]any)
	if !ok {
		return ""
	}
	preferredRaw := strings.TrimSpace(cast.ToString(executionMap["preferred_executor_id"]))
	if preferredRaw != "" {
		return preferredRaw
	}
	return strings.TrimSpace(cast.ToString(executionMap["preferredExecutorId"]))
}

func (s *Service) pickExecutorForStepDispatch(
	pluginID string,
	readyAt *time.Time,
	dependencyPreferredExecutorID string,
	loopPreferredExecutorID string,
) (executorID string, deferredByAffinity bool, blockedByLoopBinding bool) {
	loopPreferredExecutorID = strings.TrimSpace(loopPreferredExecutorID)
	if loopPreferredExecutorID != "" {
		executorID, deferredByAffinity = s.pickExecutorWithRoundAffinity(
			pluginID,
			loopPreferredExecutorID,
			readyAt,
		)
		return executorID, deferredByAffinity, false
	}
	executorID, deferredByAffinity = s.pickExecutorWithRoundAffinity(
		pluginID,
		dependencyPreferredExecutorID,
		readyAt,
	)
	return executorID, deferredByAffinity, false
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
	artifactCandidates := resolveModelArtifactCandidates(requirements)

	trainTaskID, err := s.qtx(tx).GetLatestSucceededTrainTaskIDByRound(ctx, stepPayload.RoundID)
	if err != nil {
		if err == pgx.ErrNoRows {
			currentTaskID := stepPayload.StepID
			if stepPayload.TaskID != nil {
				currentTaskID = *stepPayload.TaskID
			} else if mappedTaskID, ok, mapErr := s.resolveTaskIDForStepTx(ctx, tx, stepPayload.StepID); mapErr == nil && ok {
				currentTaskID = mappedTaskID
			}
			return nil, fmt.Errorf(
				"round 缺少成功 TRAIN 结果，无法注入模型: round_id=%s task_id=%s step_id=%s",
				stepPayload.RoundID,
				currentTaskID,
				stepPayload.StepID,
			)
		}
		return nil, err
	}
	trainStepID := uuid.Nil
	if mappedStepID, mapped, mapErr := s.resolveStepIDForTaskTx(ctx, tx, trainTaskID); mapErr != nil {
		return nil, mapErr
	} else if mapped {
		trainStepID = mappedStepID
	}
	trainTaskRow, foundTrainTask, err := s.getTaskForUpdateTx(ctx, tx, trainTaskID)
	if err != nil {
		return nil, err
	}
	if !foundTrainTask {
		return nil, fmt.Errorf("训练任务不存在: train_task_id=%s", trainTaskID)
	}
	trainParams, err := parseJSONObject(trainTaskRow.ResolvedParamsJSON)
	if err != nil {
		return nil, err
	}
	resultArtifacts, _ := trainParams["_result_artifacts"].(map[string]any)
	selectedArtifact := ""
	for _, artifactName := range artifactCandidates {
		if rawArtifact, ok := resultArtifacts[artifactName]; ok {
			if artifactMap, ok := rawArtifact.(map[string]any); ok {
				if strings.TrimSpace(cast.ToString(artifactMap["uri"])) != "" {
					selectedArtifact = artifactName
					break
				}
			}
		}
	}
	if selectedArtifact == "" {
		return nil, fmt.Errorf(
			"训练模型制品不存在: train_task_id=%s train_step_id=%s tried=%s",
			trainTaskID,
			trainStepID.String(),
			strings.Join(artifactCandidates, ","),
		)
	}

	paramsMap := injectRuntimeArtifactRefs(
		cloneMap(structToMap(stepPayload.Params)),
		trainTaskID,
		trainStepID,
		selectedArtifact,
		time.Now().UTC(),
	)

	resolvedParams, err := structpb.NewStruct(paramsMap)
	if err != nil {
		return nil, err
	}
	return resolvedParams, nil
}

func injectRuntimeArtifactRefs(
	paramsMap map[string]any,
	trainTaskID uuid.UUID,
	trainStepID uuid.UUID,
	selectedArtifact string,
	injectedAt time.Time,
) map[string]any {
	pluginParams := ensureMap(paramsMap["plugin"])
	delete(pluginParams, "model_source")
	delete(pluginParams, "model_custom_ref")
	paramsMap["plugin"] = pluginParams
	paramsMap["_runtime_artifact_refs"] = map[string]any{
		"model": map[string]any{
			"source_task_id": trainTaskID.String(),
			"artifact_name":  selectedArtifact,
			"from_step_id":   strings.TrimSpace(trainStepID.String()),
			"injected_at":    injectedAt.UTC().Format(time.RFC3339),
		},
	}
	return paramsMap
}

func (s *Service) failTaskDispatchPreflightTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	reason string,
) error {
	if err := s.updateTaskStatusTx(ctx, tx, taskID, "FAILED", reason); err != nil {
		return err
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return err
	}
	return nil
}

func (s *Service) markTaskDispatchingTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	executorID string,
	requestID string,
) (bool, error) {
	_ = requestID
	updated, err := s.qtx(tx).MarkTaskDispatchingFromReady(ctx, db.MarkTaskDispatchingFromReadyParams{
		AssignedExecutorID: toPGText(executorID),
		TaskID:             taskID,
	})
	if err != nil {
		return false, err
	}
	if updated == 0 {
		return false, nil
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) promoteTaskToReadyTx(ctx context.Context, tx pgx.Tx, taskID uuid.UUID) (bool, error) {
	updated, err := s.qtx(tx).PromoteTaskToReady(ctx, taskID)
	if err != nil {
		return false, err
	}
	if updated == 0 {
		return false, nil
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) promoteRetryingTaskToReadyTx(ctx context.Context, tx pgx.Tx, taskID uuid.UUID) (bool, error) {
	updated, err := s.qtx(tx).PromoteRetryingTaskToReady(ctx, taskID)
	if err != nil {
		return false, err
	}
	if updated == 0 {
		return false, nil
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) projectTaskToStepTx(ctx context.Context, tx pgx.Tx, taskID uuid.UUID) error {
	projected, err := s.qtx(tx).ProjectStepFromTask(ctx, taskID)
	if err != nil {
		return err
	}
	if projected == 0 {
		s.logger.Warn().
			Str("task_id", taskID.String()).
			Msg("task->step 投影缺失，已保留 task 主干状态")
	}
	return nil
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

func (s *Service) getStepPayloadByIDTx(ctx context.Context, tx pgx.Tx, taskID uuid.UUID) (stepDispatchPayload, bool, error) {
	record, err := s.qtx(tx).GetStepPayloadByTaskIDForUpdate(ctx, taskID)
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

func (s *Service) insertTaskEventTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	seq int64,
	ts time.Time,
	eventType string,
	payloadJSON string,
	requestID string,
	executionID uuid.UUID,
) (bool, error) {
	_ = requestID
	affected, err := s.qtx(tx).InsertTaskEvent(ctx, db.InsertTaskEventParams{
		EventID:     uuid.New(),
		TaskID:      taskID,
		ExecutionID: executionID,
		Seq:         int32(seq),
		Ts:          toPGTimestamp(ts),
		EventType:   eventType,
		Payload:     []byte(payloadJSON),
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
	taskID uuid.UUID,
	executionID uuid.UUID,
	attempt int,
	reason string,
) (bool, error) {
	requestID := uuid.New()
	commandID := cancelAttemptCommandID(stepID, attempt)
	inserted, err := s.insertCommandLogTx(ctx, tx, requestID, commandID)
	if err != nil {
		return false, err
	}
	if !inserted {
		return false, nil
	}

	dispatchTaskID := taskID
	stopRequestID, accepted := s.dispatcher.StopTask(dispatchTaskID.String(), executionID.String(), reason)
	detail := fmt.Sprintf(
		"已发起取消尝试 accepted=%t stop_request_id=%s task_id=%s",
		accepted,
		strings.TrimSpace(stopRequestID),
		dispatchTaskID.String(),
	)
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
	for _, stepID := range stepIDs {
		taskID, mapped, err := s.resolveTaskIDForStepTx(ctx, tx, stepID)
		if err != nil {
			return err
		}
		if !mapped {
			return fmt.Errorf("step 缺失 task 绑定: step_id=%s", stepID)
		}
		if _, err := s.qtx(tx).CancelTaskByID(ctx, db.CancelTaskByIDParams{
			LastError: toPGText(reason),
			TaskID:    taskID,
		}); err != nil {
			return err
		}
		if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
			return err
		}
	}
	return nil
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
	taskID uuid.UUID,
	step int,
	epoch *int,
	metrics map[string]float64,
	ts time.Time,
) error {
	if len(metrics) == 0 {
		return nil
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyTaskMetricPointsParams, 0, len(metrics))
	for metricName, metricValue := range metrics {
		cleanMetricName := strings.TrimSpace(metricName)
		if cleanMetricName == "" {
			continue
		}
		rows = append(rows, db.CopyTaskMetricPointsParams{
			ID:          uuid.New(),
			TaskID:      taskID,
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
	if _, err := s.qtx(tx).CopyTaskMetricPoints(ctx, rows); err != nil {
		return err
	}
	return nil
}

func (s *Service) replaceTaskCandidatesTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	candidates []*runtimecontrolv1.QueryCandidate,
) error {
	if err := s.qtx(tx).DeleteTaskCandidatesByTaskID(ctx, taskID); err != nil {
		return err
	}
	now := toPGTimestamp(time.Now().UTC())
	rows := make([]db.CopyTaskCandidateItemsParams, 0, len(candidates))
	for idx, item := range candidates {
		sampleIDText := strings.TrimSpace(item.GetSampleId())
		if sampleIDText == "" {
			continue
		}
		parsedSampleID, err := parseUUID(sampleIDText)
		if err != nil {
			continue
		}
		reasonPayload := structToMap(item.GetReason())
		reasonJSON, err := marshalJSON(reasonPayload)
		if err != nil {
			return err
		}
		predictionSnapshotJSON, err := marshalJSON(extractPredictionSnapshotFromReason(reasonPayload))
		if err != nil {
			return err
		}
		rows = append(rows, db.CopyTaskCandidateItemsParams{
			ID:                 uuid.New(),
			TaskID:             taskID,
			SampleID:           parsedSampleID,
			Rank:               int32(idx + 1),
			Score:              item.GetScore(),
			Reason:             []byte(reasonJSON),
			PredictionSnapshot: []byte(predictionSnapshotJSON),
			CreatedAt:          now,
			UpdatedAt:          now,
		})
	}
	if len(rows) > 0 {
		if _, err := s.qtx(tx).CopyTaskCandidateItems(ctx, rows); err != nil {
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
		payload := &runtimecontrolv1.TaskPayload{}
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

		if s.dispatcher.DispatchTask(row.ExecutorID, row.RequestID, payload) {
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
	taskIDs, err := s.queries.ListOrphanDispatchingTaskIDs(ctx, db.ListOrphanDispatchingTaskIDsParams{
		Cutoff:     orphanCutoff,
		LimitCount: int32(max(1, limit)),
	})
	if err != nil {
		return err
	}
	for _, taskID := range taskIDs {
		updated, err := s.queries.RecoverStaleDispatchingTaskToReady(ctx, db.RecoverStaleDispatchingTaskToReadyParams{
			LastError: toPGText("已恢复孤儿派发记录"),
			TaskID:    taskID,
		})
		if err != nil {
			return err
		}
		if updated == 0 {
			continue
		}
		if projected, projErr := s.queries.ProjectStepFromTask(ctx, taskID); projErr != nil {
			return projErr
		} else if projected == 0 {
			s.logger.Warn().
				Str("task_id", taskID.String()).
				Msg("恢复孤儿派发记录后未找到step投影")
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
	updateStateJSON, err := marshalJSON(runtimeUpdateStateToMap(register.GetUpdateState()))
	if err != nil {
		return err
	}

	return s.queries.UpsertRuntimeExecutorOnRegister(ctx, db.UpsertRuntimeExecutorOnRegisterParams{
		ExecutorRowID: uuid.New(),
		ExecutorID:    executorID,
		Version:       version,
		PluginIds:     []byte(pluginPayloadJSON),
		Resources:     []byte(resourcesJSON),
		UpdateState:   []byte(updateStateJSON),
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
	} else if phase := runtimeUpdatePhaseToText(heartbeat.GetUpdateState().GetPhase()); phase != "" && phase != "succeeded" && phase != "failed" && phase != "rolled_back" {
		status = "updating"
	}
	currentTaskID := strings.TrimSpace(heartbeat.GetCurrentTaskId())
	currentTaskUUID, err := parseNullableUUID(currentTaskID)
	if err != nil {
		return err
	}
	resourcesJSON, err := marshalJSON(resourceSummaryToMap(heartbeat.GetResources()))
	if err != nil {
		return err
	}
	updateStateJSON, err := marshalJSON(runtimeUpdateStateToMap(heartbeat.GetUpdateState()))
	if err != nil {
		return err
	}

	return s.queries.UpsertRuntimeExecutorOnHeartbeat(ctx, db.UpsertRuntimeExecutorOnHeartbeatParams{
		ExecutorRowID: uuid.New(),
		ExecutorID:    executorID,
		Status:        status,
		CurrentTaskID: currentTaskUUID,
		Resources:     []byte(resourcesJSON),
		UpdateState:   []byte(updateStateJSON),
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

	if err := s.queries.UpdateRuntimeExecutorDisconnected(ctx, db.UpdateRuntimeExecutorDisconnectedParams{
		Reason:     toNullablePGText(reason),
		ExecutorID: executorID,
	}); err != nil {
		return err
	}
	return s.recoverInFlightTasksByExecutor(ctx, executorID, "executor disconnected")
}
