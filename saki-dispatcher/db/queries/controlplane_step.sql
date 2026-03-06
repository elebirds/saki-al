-- name: ListReadyTaskIDsForDispatch :many
SELECT t.id AS id
FROM task t
LEFT JOIN step s ON s.task_id = t.id
LEFT JOIN round r ON r.id = s.round_id
LEFT JOIN loop l ON l.id = r.loop_id
WHERE (
  t.kind = 'PREDICTION'::taskkind
  AND t.status IN (
    'PENDING'::taskstatus,
    'READY'::taskstatus,
    'RETRYING'::taskstatus
  )
)
OR (
  t.kind = 'STEP'::taskkind
  AND t.status IN (
    'PENDING'::taskstatus,
    'READY'::taskstatus,
    'RETRYING'::taskstatus
  )
  AND l.lifecycle = 'RUNNING'::looplifecycle
)
ORDER BY t.created_at ASC
LIMIT sqlc.arg(limit_count)
FOR UPDATE OF t SKIP LOCKED;

-- name: GetStepPayloadByIDForUpdate :one
SELECT
  t.id AS step_id,
  t.task_id AS task_id,
  t.round_id AS round_id,
  COALESCE(k.status::text, t.state::text)::stepstatus AS status,
  t.step_type AS step_type,
  t.dispatch_kind AS dispatch_kind,
  t.round_index,
  COALESCE(k.attempt, t.attempt) AS attempt,
  t.state_version,
  COALESCE(k.updated_at, t.updated_at) AS updated_at,
  COALESCE(k.depends_on_task_ids, '[]'::jsonb) AS depends_on_task_raw,
  t.resolved_params AS params_raw,
  t.input_commit_id AS input_commit_id,
  j.loop_id AS loop_id,
  j.project_id AS project_id,
  j.plugin_id,
  j.mode AS mode,
  j.resolved_params AS round_params_raw,
  j.resources AS resources_raw,
  j.input_commit_id AS round_input_commit_id
FROM step t
JOIN round j ON j.id = t.round_id
LEFT JOIN task k ON k.id = t.task_id
WHERE t.id = sqlc.arg(step_id)::uuid
FOR UPDATE SKIP LOCKED;

-- name: GetDependencyTaskStatusesByIDs :many
SELECT status
FROM task
WHERE id = ANY(sqlc.arg(task_ids)::uuid[]);

-- name: GetLatestAssignedExecutorByTaskIDs :one
SELECT COALESCE(assigned_executor_id, '') AS assigned_executor_id
FROM task
WHERE id = ANY(sqlc.arg(task_ids)::uuid[])
ORDER BY array_position(sqlc.arg(task_ids)::uuid[], id) DESC
LIMIT 1;

-- name: PromoteStepToReady :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'PENDING'::stepstatus;

-- name: PromoteRetryingStepToReady :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'RETRYING'::stepstatus;

-- name: MarkStepDispatching :execrows
UPDATE step
SET state = 'DISPATCHING'::stepstatus,
    assigned_executor_id = sqlc.arg(assigned_executor_id),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'READY'::stepstatus;

-- name: ResetStepToReadyQueueFull :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    assigned_executor_id = NULL,
    last_error = '派发队列已满',
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state IN (
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus
  );

-- name: RecoverStaleDispatchingStepToReady :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    assigned_executor_id = NULL,
    last_error = sqlc.arg(last_error),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state IN (
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus
  );

-- name: MarkOrchestratorStepRunning :execrows
UPDATE step
SET state = 'RUNNING'::stepstatus,
    started_at = COALESCE(started_at, now()),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'READY'::stepstatus;

-- name: MarkOrchestratorStepRetrying :execrows
UPDATE step
SET state = 'RETRYING'::stepstatus,
    attempt = attempt + 1,
    last_error = sqlc.arg(last_error),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'RUNNING'::stepstatus
  AND attempt < max_attempts;

-- name: UpdateStepExecutionResultGuarded :execrows
UPDATE step
SET state = sqlc.arg(state)::stepstatus,
    last_error = sqlc.narg(last_error)::text,
    ended_at = CASE
      WHEN sqlc.arg(state)::stepstatus IN ('SUCCEEDED'::stepstatus, 'FAILED'::stepstatus, 'CANCELLED'::stepstatus, 'SKIPPED'::stepstatus)
      THEN COALESCE(ended_at, now())
      ELSE ended_at
    END,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = sqlc.arg(from_state)::stepstatus;

-- name: GetLoopQueryBatchSize :one
SELECT query_batch_size
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetSucceededScoreStepIDByRound :one
SELECT id AS step_id
FROM step
WHERE round_id = sqlc.arg(round_id)::uuid
  AND step_type = 'SCORE'::steptype
  AND state = 'SUCCEEDED'::stepstatus
ORDER BY step_index DESC
LIMIT 1;

-- name: GetLatestSucceededTrainStepIDByRound :one
SELECT id AS step_id
FROM step
WHERE round_id = sqlc.arg(round_id)::uuid
  AND step_type = 'TRAIN'::steptype
  AND state = 'SUCCEEDED'::stepstatus
ORDER BY step_index DESC
LIMIT 1;

-- name: ListTaskCandidatesByTaskID :many
SELECT
  sample_id AS sample_id,
  rank,
  score,
  reason AS reason_json,
  prediction_snapshot AS prediction_json
FROM task_candidate_item
WHERE task_id = sqlc.arg(task_id)::uuid
ORDER BY rank ASC, score DESC
LIMIT sqlc.arg(limit_count);

-- name: DeleteTaskCandidatesByTaskID :exec
DELETE FROM task_candidate_item
WHERE task_id = sqlc.arg(task_id)::uuid;

-- name: InsertTaskCandidateItem :exec
INSERT INTO task_candidate_item(
  id, task_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  sqlc.arg(candidate_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(sample_id)::uuid,
  sqlc.arg(rank),
  sqlc.arg(score),
  sqlc.arg(reason)::jsonb,
  sqlc.arg(prediction_snapshot)::jsonb,
  now(),
  now()
);

-- name: CopyTaskCandidateItems :copyfrom
INSERT INTO task_candidate_item(
  id, task_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
);

-- name: GetStepStateForUpdate :one
SELECT state
FROM step
WHERE id = sqlc.arg(step_id)::uuid
FOR UPDATE;

-- name: UpdateStepStatusFromEventGuarded :execrows
UPDATE step
SET state = sqlc.arg(state)::stepstatus,
    started_at = CASE WHEN sqlc.arg(state)::stepstatus = 'RUNNING'::stepstatus THEN COALESCE(started_at, now()) ELSE started_at END,
    ended_at = CASE WHEN sqlc.arg(state)::stepstatus IN ('SUCCEEDED'::stepstatus, 'FAILED'::stepstatus, 'CANCELLED'::stepstatus, 'SKIPPED'::stepstatus) THEN COALESCE(ended_at, now()) ELSE ended_at END,
    last_error = CASE WHEN sqlc.arg(state)::stepstatus IN ('SUCCEEDED'::stepstatus, 'FAILED'::stepstatus, 'CANCELLED'::stepstatus, 'SKIPPED'::stepstatus) THEN sqlc.narg(reason)::text ELSE last_error END,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = sqlc.arg(from_state)::stepstatus;

-- name: UpdateStepResultGuarded :execrows
UPDATE step
SET state = sqlc.arg(state)::stepstatus,
    metrics = sqlc.arg(metrics)::jsonb,
    artifacts = sqlc.arg(artifacts)::jsonb,
    last_error = sqlc.narg(error_message)::text,
    started_at = COALESCE(started_at, now()),
    ended_at = CASE WHEN sqlc.arg(state)::stepstatus IN ('SUCCEEDED'::stepstatus, 'FAILED'::stepstatus, 'CANCELLED'::stepstatus, 'SKIPPED'::stepstatus) THEN COALESCE(ended_at, now()) ELSE ended_at END,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = sqlc.arg(from_state)::stepstatus;

-- name: InsertTaskMetricPoint :exec
INSERT INTO task_metric_point(
  id, task_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
) VALUES (
  sqlc.arg(metric_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(step),
  sqlc.arg(epoch),
  sqlc.arg(metric_name),
  sqlc.arg(metric_value),
  sqlc.arg(ts),
  now(),
  now()
);

-- name: CopyTaskMetricPoints :copyfrom
INSERT INTO task_metric_point(
  id, task_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
);

-- name: GetStepArtifactsForUpdate :one
SELECT artifacts
FROM step
WHERE id = sqlc.arg(step_id)::uuid
FOR UPDATE;

-- name: UpdateStepArtifacts :exec
UPDATE step
SET artifacts = sqlc.arg(artifacts)::jsonb,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid;
