package controlplane

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/elebirds/saki/saki-dispatcher/internal/dispatch"
	runtimecontrolv1 "github.com/elebirds/saki/saki-dispatcher/internal/gen/runtimecontrolv1"
	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

type assignAckAction int

const (
	assignAckActionNoop assignAckAction = iota
	assignAckActionToReady
	assignAckActionToFailed
	assignAckActionRetryOrFail
)

type inFlightRecoveryCandidate struct {
	TaskID                uuid.UUID
	TaskStatus            db.Runtimetaskstatus
	Attempt               int
	MaxAttempts           int
	AssignedExecutorID    string
	TaskUpdatedAt         time.Time
	ExecutorOnline        bool
	ExecutorLastSeenAt    *time.Time
	ExecutorCurrentTaskID string
}

type terminalTaskResultRecoveryCandidate struct {
	LoopID                uuid.UUID
	RoundID               uuid.UUID
	LoopLifecycle         db.Looplifecycle
	LoopPhase             db.Loopphase
	LastConfirmedCommitID *uuid.UUID
	StepID                uuid.UUID
	StepType              db.Steptype
	TaskID                uuid.UUID
	CurrentExecutionID    uuid.UUID
	TaskStatus            db.Runtimetaskstatus
	TaskUpdatedAt         time.Time
	TaskEndedAt           *time.Time
}

func assignAckActionForReason(reason runtimecontrolv1.AckReason) assignAckAction {
	switch reason {
	case runtimecontrolv1.AckReason_ACK_REASON_EXECUTOR_BUSY, runtimecontrolv1.AckReason_ACK_REASON_STOPPING:
		return assignAckActionToReady
	case runtimecontrolv1.AckReason_ACK_REASON_REJECTED:
		return assignAckActionToFailed
	case runtimecontrolv1.AckReason_ACK_REASON_UNSPECIFIED:
		return assignAckActionNoop
	default:
		return assignAckActionRetryOrFail
	}
}

func (s *Service) OnAssignTaskAck(ctx context.Context, ack *dispatch.AssignTaskAckContext) error {
	if !s.dbEnabled() || ack == nil {
		return nil
	}
	if ack.Status == runtimecontrolv1.AckStatus_OK {
		return nil
	}
	taskID, err := parseUUID(strings.TrimSpace(ack.TaskID))
	if err != nil {
		return nil
	}
	executorID := strings.TrimSpace(ack.ExecutorID)
	if executorID == "" {
		return nil
	}

	tx, err := s.beginTx(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	targetStatus, changed, reasonText, err := s.applyAssignAckFailureTx(ctx, tx, taskID, executorID, ack)
	if err != nil {
		return err
	}
	if !changed {
		return tx.Commit(ctx)
	}

	if err := s.insertSystemTaskStatusEventTx(ctx, tx, taskID, targetStatus, reasonText); err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Str("target_status", strings.ToLower(string(targetStatus))).
			Msg("写入 assign_ack 系统状态事件失败")
	}
	s.logger.Warn().
		Str("task_id", taskID.String()).
		Str("executor_id", executorID).
		Str("request_id", strings.TrimSpace(ack.RequestID)).
		Str("ack_reason", strings.ToLower(strings.TrimPrefix(ack.Reason.String(), "ACK_REASON_"))).
		Str("target_status", strings.ToLower(string(targetStatus))).
		Str("detail", reasonText).
		Msg("dispatch_trace assign_task ack 触发调度状态回退")
	s.projectAndRefreshRoundBestEffortTx(ctx, tx, taskID)
	return tx.Commit(ctx)
}

func (s *Service) applyAssignAckFailureTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	executorID string,
	ack *dispatch.AssignTaskAckContext,
) (db.Runtimetaskstatus, bool, string, error) {
	taskRow, found, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return "", false, "", err
	}
	if !found {
		return "", false, "", nil
	}
	if normalizeTaskEnumText(taskRow.Status) != "DISPATCHING" {
		return "", false, "", nil
	}
	if strings.TrimSpace(taskRow.AssignedExecutorID) != executorID {
		return "", false, "", nil
	}

	reasonText := buildAssignAckFailureReason(ack.Reason, ack.Detail)
	switch assignAckActionForReason(ack.Reason) {
	case assignAckActionNoop:
		return "", false, "", nil
	case assignAckActionToReady:
		affected, err := s.qtx(tx).ResetDispatchingTaskToReadyByAck(ctx, db.ResetDispatchingTaskToReadyByAckParams{
			LastError:          toPGText(reasonText),
			TaskID:             taskID,
			AssignedExecutorID: toPGText(executorID),
			NewExecutionID:     uuid.New(),
		})
		if err != nil {
			return "", false, "", err
		}
		return taskReady, affected > 0, reasonText, nil
	case assignAckActionToFailed:
		affected, err := s.qtx(tx).FailDispatchingTaskByAck(ctx, db.FailDispatchingTaskByAckParams{
			LastError:          toPGText(reasonText),
			TaskID:             taskID,
			AssignedExecutorID: toPGText(executorID),
		})
		if err != nil {
			return "", false, "", err
		}
		return taskFailed, affected > 0, reasonText, nil
	default:
		affected, err := s.qtx(tx).RetryDispatchingTaskByAck(ctx, db.RetryDispatchingTaskByAckParams{
			LastError:          toPGText(reasonText),
			TaskID:             taskID,
			AssignedExecutorID: toPGText(executorID),
			NewExecutionID:     uuid.New(),
		})
		if err != nil {
			return "", false, "", err
		}
		if affected > 0 {
			return taskRetrying, true, reasonText, nil
		}
		affected, err = s.qtx(tx).FailDispatchingTaskByAck(ctx, db.FailDispatchingTaskByAckParams{
			LastError:          toPGText(reasonText),
			TaskID:             taskID,
			AssignedExecutorID: toPGText(executorID),
		})
		if err != nil {
			return "", false, "", err
		}
		return taskFailed, affected > 0, reasonText, nil
	}
}

func (s *Service) recoverStaleInFlightTasks(ctx context.Context, limit int) error {
	if !s.dbEnabled() {
		return nil
	}
	rows, err := s.queries.ListInFlightTaskRecoveryCandidates(ctx, int32(max(1, limit)))
	if err != nil {
		return err
	}
	now := time.Now().UTC()
	for _, row := range rows {
		candidate := mapInFlightRecoveryCandidate(row, now)
		shouldRecover, reasonText := s.shouldRecoverInFlightCandidate(now, candidate)
		if !shouldRecover {
			continue
		}
		if err := s.recoverInFlightTaskByID(ctx, candidate.TaskID, candidate.AssignedExecutorID, reasonText); err != nil {
			s.logger.Warn().
				Err(err).
				Str("task_id", candidate.TaskID.String()).
				Str("task_status", strings.ToLower(string(candidate.TaskStatus))).
				Msg("自动回收 in-flight task 失败")
		}
	}
	return nil
}

func (s *Service) recoverTerminalTasksWithoutMaterializedResult(ctx context.Context, limit int) error {
	if !s.dbEnabled() {
		return nil
	}
	rows, err := s.queries.ListLatestRoundTerminalTaskResultRecoveryCandidates(ctx, int32(max(1, limit)))
	if err != nil {
		return err
	}
	now := time.Now().UTC()
	byRound := make(map[uuid.UUID][]terminalTaskResultRecoveryCandidate, len(rows))
	roundOrder := make([]uuid.UUID, 0, len(rows))
	for _, row := range rows {
		item := mapTerminalTaskResultRecoveryCandidate(row, now)
		if !s.shouldRecoverTerminalTaskResultCandidate(now, item) {
			continue
		}
		if _, exists := byRound[item.RoundID]; !exists {
			roundOrder = append(roundOrder, item.RoundID)
		}
		byRound[item.RoundID] = append(byRound[item.RoundID], item)
	}
	for _, roundID := range roundOrder {
		items := byRound[roundID]
		if len(items) == 0 {
			continue
		}
		if err := s.recoverLatestRoundTerminalTasksWithoutResult(ctx, items); err != nil {
			s.logger.Warn().
				Err(err).
				Str("round_id", roundID.String()).
				Msg("终态无结果任务自动收敛失败")
		}
	}
	return nil
}

func (s *Service) recoverInFlightTasksByExecutor(ctx context.Context, executorID string, reason string) error {
	if !s.dbEnabled() {
		return nil
	}
	executorID = strings.TrimSpace(executorID)
	if executorID == "" {
		return nil
	}
	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "executor disconnected"
	}

	const batchSize = 128
	var firstErr error
	for {
		taskIDs, err := s.queries.ListInFlightTaskIDsByExecutor(ctx, db.ListInFlightTaskIDsByExecutorParams{
			ExecutorID: toPGText(executorID),
			LimitCount: batchSize,
		})
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			break
		}
		if len(taskIDs) == 0 {
			break
		}
		for _, taskID := range taskIDs {
			if err := s.recoverInFlightTaskByID(ctx, taskID, executorID, reason); err != nil {
				s.logger.Warn().
					Err(err).
					Str("executor_id", executorID).
					Str("task_id", taskID.String()).
					Msg("executor 断连后回收 in-flight task 失败")
				if firstErr == nil {
					firstErr = err
				}
			}
		}
		if len(taskIDs) < batchSize {
			break
		}
	}
	return firstErr
}

func (s *Service) recoverInFlightTaskByID(
	ctx context.Context,
	taskID uuid.UUID,
	expectedExecutorID string,
	reason string,
) error {
	tx, err := s.beginTx(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	taskRow, found, err := s.getTaskForUpdateTx(ctx, tx, taskID)
	if err != nil {
		return err
	}
	if !found || isTerminalTaskStatus(taskRow.Status) {
		return tx.Commit(ctx)
	}

	status, ok := runtimeTaskStatusFromText(taskRow.Status)
	if !ok {
		return tx.Commit(ctx)
	}
	if !isRecoverableInFlightStatus(status) {
		return tx.Commit(ctx)
	}

	assignedExecutorID := strings.TrimSpace(taskRow.AssignedExecutorID)
	expectedExecutorID = strings.TrimSpace(expectedExecutorID)
	if expectedExecutorID != "" && assignedExecutorID != expectedExecutorID {
		return tx.Commit(ctx)
	}

	reason = strings.TrimSpace(reason)
	if reason == "" {
		reason = "in-flight recovery"
	}
	targetStatus, changed, err := s.applyInFlightRecoveryTx(ctx, tx, taskID, status, assignedExecutorID, reason)
	if err != nil {
		return err
	}
	if !changed {
		return tx.Commit(ctx)
	}

	if err := s.insertSystemTaskStatusEventTx(ctx, tx, taskID, targetStatus, reason); err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Str("target_status", strings.ToLower(string(targetStatus))).
			Msg("写入 in-flight recovery 系统状态事件失败")
	}
	s.projectAndRefreshRoundBestEffortTx(ctx, tx, taskID)
	return tx.Commit(ctx)
}

func (s *Service) recoverLatestRoundTerminalTasksWithoutResult(
	ctx context.Context,
	items []terminalTaskResultRecoveryCandidate,
) error {
	if len(items) == 0 {
		return nil
	}
	loopID := items[0].LoopID
	roundID := items[0].RoundID
	tx, err := s.beginTx(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	loop, found, err := s.lockLoop(ctx, tx, loopID)
	if err != nil {
		return err
	}
	if !found {
		return tx.Commit(ctx)
	}
	if loop.Lifecycle != lifecycleRunning && loop.Lifecycle != lifecycleFailed {
		return tx.Commit(ctx)
	}
	latestRound, hasRound, err := s.getLatestRoundByLoopTx(ctx, tx, loop.ID)
	if err != nil {
		return err
	}
	if !hasRound || latestRound.ID != roundID {
		return tx.Commit(ctx)
	}
	stateRows, err := s.qtx(tx).CountTaskStatesByRound(ctx, roundID)
	if err != nil {
		return err
	}
	if roundCountsHaveInFlight(stateRows) {
		return tx.Commit(ctx)
	}

	reasonText := terminalReasonTaskResultNotMaterialized
	changedTaskIDs := make([]uuid.UUID, 0, len(items))
	for _, item := range items {
		affected, err := s.qtx(tx).RecoverTerminalTaskWithoutResultToFailed(ctx, db.RecoverTerminalTaskWithoutResultToFailedParams{
			RecoveryReason:     reasonText,
			LastError:          toPGText(reasonText),
			TaskID:             item.TaskID,
			CurrentExecutionID: item.CurrentExecutionID,
			FromStatus:         item.TaskStatus,
		})
		if err != nil {
			return err
		}
		if affected == 0 {
			continue
		}
		changedTaskIDs = append(changedTaskIDs, item.TaskID)
		if err := s.insertSystemTaskStatusEventTx(ctx, tx, item.TaskID, taskFailed, reasonText); err != nil {
			s.logger.Warn().
				Err(err).
				Str("task_id", item.TaskID.String()).
				Msg("写入终态无结果恢复系统事件失败")
		}
	}
	if len(changedTaskIDs) == 0 {
		return tx.Commit(ctx)
	}
	for _, taskID := range changedTaskIDs {
		if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
			return err
		}
	}
	roundStatus, err := s.refreshRoundAggregateTx(ctx, tx, roundID)
	if err != nil {
		return err
	}
	if roundStatus == roundFailed {
		if err := s.qtx(tx).UpdateRoundStateWithReason(ctx, db.UpdateRoundStateWithReasonParams{
			State:          roundFailed,
			TerminalReason: toPGText(reasonText),
			RoundID:        roundID,
		}); err != nil {
			return err
		}
		if err := s.updateLoopRuntime(ctx, tx, loop.ID, lifecycleFailed, loop.Phase, reasonText, loop.LastConfirmedCommitID, nil); err != nil {
			return err
		}
	}
	s.logger.Warn().
		Str("loop_id", loop.ID.String()).
		Str("round_id", roundID.String()).
		Int("recovered_task_count", len(changedTaskIDs)).
		Msg("检测到终态无结果任务，已收敛为 FAILED")
	return tx.Commit(ctx)
}

func (s *Service) applyInFlightRecoveryTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	status db.Runtimetaskstatus,
	assignedExecutorID string,
	reason string,
) (db.Runtimetaskstatus, bool, error) {
	if isPreRunTaskStatus(status) {
		affected, err := s.qtx(tx).RecoverPreRunTaskToReady(ctx, db.RecoverPreRunTaskToReadyParams{
			LastError:          toPGText(reason),
			TaskID:             taskID,
			AssignedExecutorID: assignedExecutorID,
			NewExecutionID:     uuid.New(),
		})
		if err != nil {
			return "", false, err
		}
		return taskReady, affected > 0, nil
	}
	if status != taskRunning {
		return "", false, nil
	}

	affected, err := s.qtx(tx).RecoverRunningTaskToRetrying(ctx, db.RecoverRunningTaskToRetryingParams{
		LastError:          toPGText(reason),
		TaskID:             taskID,
		AssignedExecutorID: assignedExecutorID,
		NewExecutionID:     uuid.New(),
	})
	if err != nil {
		return "", false, err
	}
	if affected > 0 {
		return taskRetrying, true, nil
	}
	affected, err = s.qtx(tx).RecoverRunningTaskToFailed(ctx, db.RecoverRunningTaskToFailedParams{
		LastError:          toPGText(reason),
		TaskID:             taskID,
		AssignedExecutorID: assignedExecutorID,
	})
	if err != nil {
		return "", false, err
	}
	return taskFailed, affected > 0, nil
}

func (s *Service) shouldRecoverInFlightCandidate(now time.Time, item inFlightRecoveryCandidate) (bool, string) {
	if !isRecoverableInFlightStatus(item.TaskStatus) {
		return false, ""
	}
	timeout := s.inFlightPreRunTimeout
	if item.TaskStatus == taskRunning {
		timeout = s.inFlightRunningTimeout
	}
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	if now.Sub(item.TaskUpdatedAt.UTC()) < timeout {
		return false, ""
	}

	executorID := strings.TrimSpace(item.AssignedExecutorID)
	if executorID == "" {
		return true, fmt.Sprintf("in-flight timeout without assigned executor status=%s", strings.ToLower(string(item.TaskStatus)))
	}
	if !item.ExecutorOnline {
		return true, fmt.Sprintf("executor offline after timeout executor_id=%s", executorID)
	}
	if item.ExecutorLastSeenAt == nil || item.ExecutorLastSeenAt.IsZero() {
		return true, fmt.Sprintf("executor heartbeat missing after timeout executor_id=%s", executorID)
	}
	if s.heartbeatTimeout > 0 && now.Sub(item.ExecutorLastSeenAt.UTC()) > s.heartbeatTimeout {
		return true, fmt.Sprintf("executor heartbeat timeout executor_id=%s", executorID)
	}

	currentTaskID := strings.TrimSpace(item.ExecutorCurrentTaskID)
	if currentTaskID != item.TaskID.String() {
		return true, fmt.Sprintf(
			"executor current_task mismatch executor_id=%s expected=%s actual=%s",
			executorID,
			item.TaskID.String(),
			currentTaskID,
		)
	}
	return false, ""
}

func (s *Service) insertSystemTaskStatusEventTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
	status db.Runtimetaskstatus,
	reason string,
) error {
	statusText := strings.ToLower(strings.TrimSpace(string(status)))
	if statusText == "" {
		return nil
	}
	reason = strings.TrimSpace(reason)
	payloadJSON, err := marshalJSON(map[string]any{
		"status": statusText,
		"reason": reason,
		"source": "dispatcher",
	})
	if err != nil {
		return err
	}
	ts := toPGTimestamp(time.Now().UTC())
	for retry := 0; retry < 3; retry++ {
		affected, err := s.qtx(tx).InsertTaskStatusSystemEvent(ctx, db.InsertTaskStatusSystemEventParams{
			EventID: uuid.New(),
			TaskID:  taskID,
			Ts:      ts,
			Payload: []byte(payloadJSON),
		})
		if err != nil {
			return err
		}
		if affected > 0 {
			return nil
		}
	}
	return nil
}

func (s *Service) projectAndRefreshRoundBestEffortTx(ctx context.Context, tx pgx.Tx, taskID uuid.UUID) {
	stepID, found, err := s.resolveStepIDForTaskTx(ctx, tx, taskID)
	if err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Msg("查询 step 投影映射失败，跳过 step/round 刷新")
		return
	}
	if !found {
		return
	}
	if err := s.projectTaskToStepTx(ctx, tx, taskID); err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Str("step_id", stepID.String()).
			Msg("task->step 投影失败，已保留 task 主干状态")
	}
	roundID, err := s.findRoundIDByStep(ctx, tx, stepID)
	if err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Str("step_id", stepID.String()).
			Msg("查找 round 映射失败，跳过 round 聚合刷新")
		return
	}
	if roundID == nil {
		return
	}
	if _, err := s.refreshRoundAggregateTx(ctx, tx, *roundID); err != nil {
		s.logger.Warn().
			Err(err).
			Str("task_id", taskID.String()).
			Str("round_id", roundID.String()).
			Msg("刷新 round 聚合失败，已保留 task 主干状态")
	}
}

func (s *Service) shouldRecoverTerminalTaskResultCandidate(
	now time.Time,
	item terminalTaskResultRecoveryCandidate,
) bool {
	if item.TaskStatus == "" || !isTerminalTaskLifecycle(item.TaskStatus) {
		return false
	}
	refTime := item.TaskUpdatedAt.UTC()
	if item.TaskEndedAt != nil && !item.TaskEndedAt.IsZero() {
		refTime = item.TaskEndedAt.UTC()
	}
	grace := s.terminalResultRecoveryGrace
	if grace <= 0 {
		grace = 2 * time.Minute
	}
	return now.Sub(refTime) >= grace
}

func mapInFlightRecoveryCandidate(row db.ListInFlightTaskRecoveryCandidatesRow, now time.Time) inFlightRecoveryCandidate {
	item := inFlightRecoveryCandidate{
		TaskID:                row.TaskID,
		TaskStatus:            row.TaskStatus,
		Attempt:               int(row.Attempt),
		MaxAttempts:           int(row.MaxAttempts),
		AssignedExecutorID:    strings.TrimSpace(row.AssignedExecutorID),
		ExecutorOnline:        row.ExecutorOnline,
		ExecutorLastSeenAt:    timestampPtr(row.ExecutorLastSeenAt),
		ExecutorCurrentTaskID: strings.TrimSpace(row.ExecutorCurrentTaskID),
		TaskUpdatedAt:         now,
	}
	if updatedAt := timestampPtr(row.TaskUpdatedAt); updatedAt != nil {
		item.TaskUpdatedAt = updatedAt.UTC()
	}
	return item
}

func mapTerminalTaskResultRecoveryCandidate(
	row db.ListLatestRoundTerminalTaskResultRecoveryCandidatesRow,
	now time.Time,
) terminalTaskResultRecoveryCandidate {
	item := terminalTaskResultRecoveryCandidate{
		LoopID:                row.LoopID,
		RoundID:               row.RoundID,
		LoopLifecycle:         row.LoopLifecycle,
		LoopPhase:             row.LoopPhase,
		LastConfirmedCommitID: row.LastConfirmedCommitID,
		StepID:                row.StepID,
		StepType:              row.StepType,
		TaskID:                row.TaskID,
		CurrentExecutionID:    row.CurrentExecutionID,
		TaskStatus:            row.TaskStatus,
		TaskUpdatedAt:         now,
		TaskEndedAt:           timestampPtr(row.TaskEndedAt),
	}
	if updatedAt := timestampPtr(row.TaskUpdatedAt); updatedAt != nil {
		item.TaskUpdatedAt = updatedAt.UTC()
	}
	return item
}

func roundCountsHaveInFlight(rows []db.CountTaskStatesByRoundRow) bool {
	for _, row := range rows {
		switch row.TaskStatus {
		case taskDispatching, taskSyncingEnv, taskProbingRt, taskBindingDev, taskRunning, taskRetrying:
			return true
		}
	}
	return false
}

func isPreRunTaskStatus(status db.Runtimetaskstatus) bool {
	switch status {
	case taskDispatching, taskSyncingEnv, taskProbingRt, taskBindingDev:
		return true
	default:
		return false
	}
}

func isRecoverableInFlightStatus(status db.Runtimetaskstatus) bool {
	return isPreRunTaskStatus(status) || status == taskRunning
}

func buildAssignAckFailureReason(reason runtimecontrolv1.AckReason, detail string) string {
	reasonText := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(reason.String(), "ACK_REASON_")))
	if reasonText == "" || reasonText == "ack_reason_unspecified" {
		reasonText = "unspecified"
	}
	detail = strings.TrimSpace(detail)
	if detail == "" {
		return fmt.Sprintf("assign task rejected: reason=%s", reasonText)
	}
	return fmt.Sprintf("assign task rejected: reason=%s detail=%s", reasonText, detail)
}
