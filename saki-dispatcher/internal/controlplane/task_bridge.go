package controlplane

import (
	"context"
	"errors"
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

func (s *Service) createStepTaskTx(
	ctx context.Context,
	tx pgx.Tx,
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
		TaskID:           taskID,
		ProjectID:        projectID,
		TaskType:         db.Runtimetasktype(string(stepType)),
		PluginID:         pluginID,
		DependsOnTaskIds: []byte(dependencyTaskIDsJSON),
		InputCommitID:    inputCommitID,
		ResolvedParams:   resolvedParams,
		MaxAttempts:      int32(maxAttempts),
	})
	if err != nil {
		return uuid.Nil, err
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
