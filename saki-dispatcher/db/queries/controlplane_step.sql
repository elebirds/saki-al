-- name: ListPendingStepIDs :many
SELECT s.id AS id
FROM step s
JOIN round r ON r.id = s.round_id
JOIN loop l ON l.id = r.loop_id
WHERE s.state = 'PENDING'::stepstatus
  AND l.status = 'RUNNING'::loopstatus
ORDER BY s.created_at ASC
LIMIT sqlc.arg(limit_count);

-- name: ListReadyStepIDsForUpdateSkipLocked :many
SELECT s.id AS id
FROM step s
JOIN round r ON r.id = s.round_id
JOIN loop l ON l.id = r.loop_id
WHERE s.state = 'READY'::stepstatus
  AND l.status = 'RUNNING'::loopstatus
ORDER BY s.created_at ASC
LIMIT sqlc.arg(limit_count)
FOR UPDATE OF s SKIP LOCKED;

-- name: ListRetryingStepIDsDueForUpdateSkipLocked :many
SELECT s.id AS id
FROM step s
JOIN round r ON r.id = s.round_id
JOIN loop l ON l.id = r.loop_id
WHERE s.state = 'RETRYING'::stepstatus
  AND l.status = 'RUNNING'::loopstatus
  AND s.updated_at <= now() - (
    CASE
      WHEN s.attempt <= 1 THEN interval '1 second'
      WHEN s.attempt = 2 THEN interval '2 seconds'
      WHEN s.attempt = 3 THEN interval '4 seconds'
      WHEN s.attempt = 4 THEN interval '8 seconds'
      WHEN s.attempt = 5 THEN interval '16 seconds'
      ELSE interval '30 seconds'
    END
  )
ORDER BY s.updated_at ASC
LIMIT sqlc.arg(limit_count)
FOR UPDATE OF s SKIP LOCKED;

-- name: GetStepPayloadByIDForUpdate :one
SELECT
  t.id AS step_id,
  t.round_id AS round_id,
  t.state AS status,
  t.step_type AS step_type,
  t.dispatch_kind AS dispatch_kind,
  t.round_index,
  t.attempt,
  t.state_version,
  t.depends_on_step_ids AS depends_on_raw,
  t.resolved_params AS params_raw,
  t.dataset_manifest_ref,
  t.snapshot_id,
  t.env_overrides AS env_overrides_raw,
  t.runtime_hints AS runtime_hints_raw,
  t.kernel_capability_requirements AS kernel_capability_requirements_raw,
  t.gpu_exclusive,
  t.kernel_id,
  t.kernel_version,
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
WHERE t.id = sqlc.arg(step_id)::uuid
FOR UPDATE SKIP LOCKED;

-- name: GetDependencyStatesByIDs :many
SELECT state
FROM step
WHERE id = ANY(sqlc.arg(step_ids)::uuid[]);

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
    dispatch_request_id = sqlc.arg(dispatch_request_id),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'READY'::stepstatus;

-- name: ResetStepToReadyQueueFull :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    assigned_executor_id = NULL,
    dispatch_request_id = NULL,
    last_error = '派发队列已满',
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'DISPATCHING'::stepstatus;

-- name: RecoverStaleDispatchingStepToReady :execrows
UPDATE step
SET state = 'READY'::stepstatus,
    assigned_executor_id = NULL,
    dispatch_request_id = NULL,
    last_error = sqlc.arg(last_error),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = 'DISPATCHING'::stepstatus;

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
    output_commit_id = sqlc.narg(output_commit_id)::uuid,
    ended_at = CASE
      WHEN sqlc.arg(state)::stepstatus IN ('SUCCEEDED'::stepstatus, 'FAILED'::stepstatus, 'CANCELLED'::stepstatus, 'SKIPPED'::stepstatus)
      THEN COALESCE(ended_at, now())
      ELSE ended_at
    END,
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state = sqlc.arg(from_state)::stepstatus;

-- name: UpdateRoundOutputCommit :exec
UPDATE round
SET output_commit_id = sqlc.narg(output_commit_id)::uuid,
    updated_at = now()
WHERE id = sqlc.arg(round_id)::uuid;

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

-- name: ListStepCandidatesByStepID :many
SELECT
  sample_id AS sample_id,
  rank,
  score,
  reason AS reason_json,
  prediction_snapshot AS prediction_json
FROM step_candidate_item
WHERE step_id = sqlc.arg(step_id)::uuid
ORDER BY rank ASC, score DESC
LIMIT sqlc.arg(limit_count);

-- name: DeleteStepCandidatesByStepID :exec
DELETE FROM step_candidate_item
WHERE step_id = sqlc.arg(step_id)::uuid;

-- name: InsertStepCandidateItem :exec
INSERT INTO step_candidate_item(
  id, step_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  sqlc.arg(candidate_id)::uuid,
  sqlc.arg(step_id)::uuid,
  sqlc.arg(sample_id)::uuid,
  sqlc.arg(rank),
  sqlc.arg(score),
  sqlc.arg(reason)::jsonb,
  sqlc.arg(prediction_snapshot)::jsonb,
  now(),
  now()
);

-- name: CopyStepCandidateItems :copyfrom
INSERT INTO step_candidate_item(
  id, step_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
);

-- name: GetLoopRuntimeConfig :one
SELECT
  project_id AS project_id,
  branch_id AS branch_id,
  config,
  query_batch_size
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetLoopBranchID :one
SELECT branch_id AS branch_id
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetLatestActivateOutputCommitByRound :one
SELECT output_commit_id
FROM step
WHERE round_id = sqlc.arg(round_id)::uuid
  AND step_type = 'ACTIVATE_SAMPLES'::steptype
  AND state = 'SUCCEEDED'::stepstatus
ORDER BY step_index DESC
LIMIT 1;

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

-- name: InsertStepMetricPoint :exec
INSERT INTO step_metric_point(
  id, step_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
) VALUES (
  sqlc.arg(metric_id)::uuid,
  sqlc.arg(step_id)::uuid,
  sqlc.arg(step),
  sqlc.arg(epoch),
  sqlc.arg(metric_name),
  sqlc.arg(metric_value),
  sqlc.arg(ts),
  now(),
  now()
);

-- name: CopyStepMetricPoints :copyfrom
INSERT INTO step_metric_point(
  id, step_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
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

-- name: UpdateStepDatasetBinding :exec
UPDATE step
SET dataset_manifest_ref = sqlc.narg(dataset_manifest_ref)::text,
    snapshot_id = sqlc.narg(snapshot_id)::uuid,
    env_overrides = sqlc.arg(env_overrides)::jsonb,
    runtime_hints = sqlc.arg(runtime_hints)::jsonb,
    kernel_capability_requirements = sqlc.arg(kernel_capability_requirements)::jsonb,
    gpu_exclusive = sqlc.arg(gpu_exclusive),
    kernel_id = sqlc.narg(kernel_id)::text,
    kernel_version = sqlc.narg(kernel_version)::text,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid;
