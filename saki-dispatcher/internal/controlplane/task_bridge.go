package controlplane

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	db "github.com/elebirds/saki/saki-dispatcher/internal/gen/sqlc"
)

type runtimeTaskRow struct {
	ID                 uuid.UUID
	ProjectID          uuid.UUID
	Kind               string
	TaskType           string
	Status             string
	PluginID           string
	InputCommitID      *uuid.UUID
	ResolvedParamsJSON []byte
	Attempt            int
	MaxAttempts        int
	AssignedExecutorID string
	LastError          string
}

func (s *Service) resolveStepIDForTaskTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
) (uuid.UUID, bool, error) {
	mappedStepID, err := s.qtx(tx).GetStepIDByTaskID(ctx, taskID)
	if err == nil {
		return mappedStepID, true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, false, nil
	}
	return uuid.Nil, false, err
}

func (s *Service) resolveTaskIDForStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
) (uuid.UUID, bool, error) {
	taskID, err := s.qtx(tx).GetTaskIDByStepID(ctx, stepID)
	if err == nil {
		if taskID == nil {
			return uuid.Nil, false, nil
		}
		return *taskID, true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, false, nil
	}
	return uuid.Nil, false, err
}

func (s *Service) resolveDependencyTaskIDsByStepDependenciesTx(
	ctx context.Context,
	tx pgx.Tx,
	dependencyStepIDs []uuid.UUID,
) ([]uuid.UUID, error) {
	if len(dependencyStepIDs) == 0 {
		return nil, nil
	}

	rows, err := s.qtx(tx).ListStepTaskBindingsByStepIDs(ctx, dependencyStepIDs)
	if err != nil {
		return nil, err
	}

	taskByStepID := make(map[uuid.UUID]uuid.UUID, len(dependencyStepIDs))
	for _, row := range rows {
		if row.TaskID != nil {
			taskByStepID[row.StepID] = *row.TaskID
		}
	}

	dependencyTaskIDs := make([]uuid.UUID, 0, len(dependencyStepIDs))
	for _, stepID := range dependencyStepIDs {
		if taskID, ok := taskByStepID[stepID]; ok {
			dependencyTaskIDs = append(dependencyTaskIDs, taskID)
			continue
		}
		return nil, fmt.Errorf("task binding missing for step dependency: step_id=%s", stepID.String())
	}
	return dependencyTaskIDs, nil
}

func (s *Service) ensureTaskBindingForStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	projectID uuid.UUID,
	stepType db.Steptype,
	pluginID string,
	inputCommitID *uuid.UUID,
	dependencyTaskIDs []uuid.UUID,
	resolvedParams []byte,
	maxAttempts int,
) (uuid.UUID, error) {
	taskID := uuid.New()
	if maxAttempts <= 0 {
		maxAttempts = 1
	}
	pluginID = strings.TrimSpace(pluginID)
	if dependencyTaskIDs == nil {
		dependencyTaskIDs = make([]uuid.UUID, 0)
	}
	dependencyTaskIDsJSON, err := marshalJSON(dependencyTaskIDs)
	if err != nil {
		return uuid.Nil, err
	}

	err = s.qtx(tx).InsertStepTask(ctx, db.InsertStepTaskParams{
		TaskID:            taskID,
		ProjectID:         projectID,
		TaskType:          db.Runtimetasktype(string(stepType)),
		PluginID:          pluginID,
		DependsOnTaskIds:  []byte(dependencyTaskIDsJSON),
		InputCommitID:     inputCommitID,
		ResolvedParams:    resolvedParams,
		MaxAttempts:       int32(maxAttempts),
	})
	if err != nil {
		return uuid.Nil, err
	}

	bound, err := s.qtx(tx).BindTaskToStep(ctx, db.BindTaskToStepParams{
		TaskID: taskID,
		StepID: stepID,
	})
	if err != nil {
		_, _ = s.qtx(tx).DeleteTaskByID(ctx, taskID)
		return uuid.Nil, err
	}
	if bound == 0 {
		_, _ = s.qtx(tx).DeleteTaskByID(ctx, taskID)
		return uuid.Nil, fmt.Errorf("step not found when binding task: step_id=%s", stepID.String())
	}
	return taskID, nil
}

func normalizeTaskEnumText(raw string) string {
	return strings.ToUpper(strings.TrimSpace(raw))
}

func isTerminalTaskStatus(raw string) bool {
	switch normalizeTaskEnumText(raw) {
	case "SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED":
		return true
	default:
		return false
	}
}

func (s *Service) getTaskForUpdateTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
) (runtimeTaskRow, bool, error) {
	record, err := s.qtx(tx).GetTaskForUpdate(ctx, taskID)
	if err == nil {
		return runtimeTaskRow{
			ID:                 record.ID,
			ProjectID:          record.ProjectID,
			Kind:               record.Kind,
			TaskType:           record.TaskType,
			Status:             record.Status,
			PluginID:           record.PluginID,
			InputCommitID:      record.InputCommitID,
			ResolvedParamsJSON: record.ResolvedParamsJson,
			Attempt:            int(record.Attempt),
			MaxAttempts:        int(record.MaxAttempts),
			AssignedExecutorID: record.AssignedExecutorID,
			LastError:          record.LastError,
		}, true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return runtimeTaskRow{}, false, nil
	}
	return runtimeTaskRow{}, false, err
}
