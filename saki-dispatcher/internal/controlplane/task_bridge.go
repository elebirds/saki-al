package controlplane

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

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

const (
	pgErrCodeUndefinedColumn = "42703"
	pgErrCodeUndefinedTable  = "42P01"
	pgErrCodeUndefinedObject = "42704"
	pgErrCodeTypeMismatch    = "42804"
	pgErrCodeInvalidTextRep  = "22P02"
)

func isTaskBridgeSchemaErr(err error) bool {
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) {
		return false
	}
	return pgErr.Code == pgErrCodeUndefinedColumn || pgErr.Code == pgErrCodeUndefinedTable
}

func isTaskBridgeCompatErr(err error) bool {
	if isTaskBridgeSchemaErr(err) {
		return true
	}
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) {
		return false
	}
	switch pgErr.Code {
	case pgErrCodeUndefinedObject, pgErrCodeTypeMismatch, pgErrCodeInvalidTextRep:
		return true
	default:
		return false
	}
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

func (s *Service) ensureTaskBindingForStepTx(
	ctx context.Context,
	tx pgx.Tx,
	stepID uuid.UUID,
	projectID uuid.UUID,
	stepType db.Steptype,
	pluginID string,
	inputCommitID *uuid.UUID,
	resolvedParams []byte,
	maxAttempts int,
) (uuid.UUID, bool, error) {
	taskID := uuid.New()
	if maxAttempts <= 0 {
		maxAttempts = 1
	}
	pluginID = strings.TrimSpace(pluginID)

	_, err := tx.Exec(
		ctx,
		`INSERT INTO task(
		  created_at, updated_at, id, project_id, kind, task_type, status,
		  plugin_id, input_commit_id, resolved_params, assigned_executor_id,
		  attempt, max_attempts, started_at, ended_at, last_error
		) VALUES (
		  now(), now(), $1, $2, 'STEP'::taskkind, $3::tasktype, 'PENDING'::taskstatus,
		  $4, $5, $6::jsonb, NULL, 1, $7, NULL, NULL, NULL
		)`,
		taskID,
		projectID,
		string(stepType),
		pluginID,
		inputCommitID,
		resolvedParams,
		maxAttempts,
	)
	if err != nil {
		if isTaskBridgeCompatErr(err) {
			return uuid.Nil, false, nil
		}
		return uuid.Nil, false, err
	}

	_, err = tx.Exec(ctx, "UPDATE step SET task_id = $1 WHERE id = $2", taskID, stepID)
	if err != nil {
		if isTaskBridgeCompatErr(err) {
			_, _ = tx.Exec(ctx, "DELETE FROM task WHERE id = $1", taskID)
			return uuid.Nil, false, nil
		}
		return uuid.Nil, false, err
	}
	return taskID, true, nil
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
	row := runtimeTaskRow{}
	err := tx.QueryRow(
		ctx,
		`SELECT
		  id,
		  project_id,
		  kind::text,
		  task_type::text,
		  status::text,
		  plugin_id,
		  input_commit_id,
		  COALESCE(resolved_params, '{}'::jsonb),
		  attempt,
		  max_attempts,
		  COALESCE(assigned_executor_id, ''),
		  COALESCE(last_error, '')
		FROM task
		WHERE id = $1
		FOR UPDATE`,
		taskID,
	).Scan(
		&row.ID,
		&row.ProjectID,
		&row.Kind,
		&row.TaskType,
		&row.Status,
		&row.PluginID,
		&row.InputCommitID,
		&row.ResolvedParamsJSON,
		&row.Attempt,
		&row.MaxAttempts,
		&row.AssignedExecutorID,
		&row.LastError,
	)
	if err == nil {
		return row, true, nil
	}
	if errors.Is(err, pgx.ErrNoRows) || isTaskBridgeCompatErr(err) {
		return runtimeTaskRow{}, false, nil
	}
	return runtimeTaskRow{}, false, err
}
