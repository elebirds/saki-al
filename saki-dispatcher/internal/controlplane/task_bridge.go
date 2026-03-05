package controlplane

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

const (
	pgErrCodeUndefinedColumn = "42703"
	pgErrCodeUndefinedTable  = "42P01"
)

func isTaskBridgeSchemaErr(err error) bool {
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) {
		return false
	}
	return pgErr.Code == pgErrCodeUndefinedColumn || pgErr.Code == pgErrCodeUndefinedTable
}

func (s *Service) resolveStepIDForTaskTx(
	ctx context.Context,
	tx pgx.Tx,
	taskID uuid.UUID,
) (uuid.UUID, bool, error) {
	var mappedStepID uuid.UUID
	err := tx.QueryRow(ctx, "SELECT id FROM step WHERE task_id = $1 LIMIT 1", taskID).Scan(&mappedStepID)
	switch {
	case err == nil:
		return mappedStepID, true, nil
	case errors.Is(err, pgx.ErrNoRows):
		// Compatible fallback: before task hard-cut, runtime task_id was directly step.id.
	case isTaskBridgeSchemaErr(err):
		// Schema not yet migrated on this environment; fallback to legacy behavior.
	default:
		return uuid.Nil, false, err
	}

	err = tx.QueryRow(ctx, "SELECT id FROM step WHERE id = $1 LIMIT 1", taskID).Scan(&mappedStepID)
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
	var taskID *uuid.UUID
	err := tx.QueryRow(ctx, "SELECT task_id FROM step WHERE id = $1", stepID).Scan(&taskID)
	if err == nil {
		if taskID == nil {
			return uuid.Nil, false, nil
		}
		return *taskID, true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) || isTaskBridgeSchemaErr(err) {
		return uuid.Nil, false, nil
	}
	return uuid.Nil, false, err
}

func (s *Service) resolveTaskIDsForStepDependenciesTx(
	ctx context.Context,
	tx pgx.Tx,
	dependencyStepIDs []uuid.UUID,
) ([]string, error) {
	if len(dependencyStepIDs) == 0 {
		return nil, nil
	}

	rows, err := tx.Query(
		ctx,
		"SELECT id, task_id FROM step WHERE id = ANY($1::uuid[])",
		dependencyStepIDs,
	)
	if err != nil {
		if isTaskBridgeSchemaErr(err) {
			return uuidSliceToStringSlice(dependencyStepIDs), nil
		}
		return nil, err
	}
	defer rows.Close()

	taskByStepID := make(map[uuid.UUID]uuid.UUID, len(dependencyStepIDs))
	for rows.Next() {
		var stepID uuid.UUID
		var taskID *uuid.UUID
		if scanErr := rows.Scan(&stepID, &taskID); scanErr != nil {
			return nil, scanErr
		}
		if taskID != nil {
			taskByStepID[stepID] = *taskID
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	dependencyTaskIDs := make([]string, 0, len(dependencyStepIDs))
	for _, stepID := range dependencyStepIDs {
		if taskID, ok := taskByStepID[stepID]; ok {
			dependencyTaskIDs = append(dependencyTaskIDs, taskID.String())
			continue
		}
		dependencyTaskIDs = append(dependencyTaskIDs, stepID.String())
	}
	return dependencyTaskIDs, nil
}
