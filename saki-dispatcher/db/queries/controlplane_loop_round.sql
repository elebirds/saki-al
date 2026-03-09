-- name: TryLoopAdvisoryXactLock :one
SELECT pg_try_advisory_xact_lock(sqlc.arg(lock_key))::bool AS locked;

-- name: TryDispatchAdvisoryLock :one
SELECT pg_try_advisory_lock(sqlc.arg(lock_key))::bool AS locked;

-- name: ReleaseDispatchAdvisoryLock :one
SELECT pg_advisory_unlock(sqlc.arg(lock_key))::bool AS unlocked;

-- name: GetLoopForUpdate :one
SELECT
  id,
  project_id,
  branch_id,
  mode,
  phase,
  lifecycle,
  current_iteration,
  max_rounds,
  query_batch_size,
  min_new_labels_per_round,
  model_arch,
  config,
  last_confirmed_commit_id,
  pause_reason
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid
FOR UPDATE;

-- name: GetLoopByID :one
SELECT
  id,
  project_id,
  branch_id,
  mode,
  phase,
  lifecycle,
  current_iteration,
  max_rounds,
  query_batch_size,
  min_new_labels_per_round,
  model_arch,
  config,
  last_confirmed_commit_id,
  pause_reason
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetLatestRoundByLoop :one
SELECT
  id,
  round_index,
  attempt_index,
  state AS summary_status,
  ended_at,
  confirmed_at,
  confirmed_revealed_count,
  confirmed_selected_count,
  confirmed_effective_min_required
FROM round
WHERE loop_id = sqlc.arg(loop_id)::uuid
ORDER BY round_index DESC, attempt_index DESC, created_at DESC
LIMIT 1;

-- name: GetRoundForRetry :one
SELECT
  id,
  loop_id,
  round_index,
  attempt_index,
  state
FROM round
WHERE id = sqlc.arg(round_id)::uuid
FOR UPDATE;

-- name: GetNextRoundIndex :one
SELECT COALESCE(MAX(round_index), 0)::int + 1 AS next_round_index
FROM round
WHERE loop_id = sqlc.arg(loop_id)::uuid;

-- name: GetNextRoundAttemptIndex :one
SELECT COALESCE(MAX(attempt_index), 0)::int + 1 AS next_attempt_index
FROM round
WHERE loop_id = sqlc.arg(loop_id)::uuid
  AND round_index = sqlc.arg(round_index);

-- name: InsertRound :exec
INSERT INTO round(
  id, project_id, loop_id, round_index, attempt_index, mode, state, step_counts, plugin_id,
  resolved_params, resources, input_commit_id, retry_of_round_id, retry_reason, terminal_reason,
  confirmed_revealed_count, confirmed_selected_count, confirmed_effective_min_required,
  final_metrics, final_artifacts,
  created_at, updated_at
) VALUES (
  sqlc.arg(round_id)::uuid,
  sqlc.arg(project_id)::uuid,
  sqlc.arg(loop_id)::uuid,
  sqlc.arg(round_index),
  sqlc.arg(attempt_index),
  sqlc.arg(mode)::loopmode,
  sqlc.arg(state)::roundstatus,
  sqlc.arg(step_counts)::jsonb,
  sqlc.arg(plugin_id),
  sqlc.arg(resolved_params)::jsonb,
  sqlc.arg(resources)::jsonb,
  sqlc.narg(input_commit_id)::uuid,
  sqlc.narg(retry_of_round_id)::uuid,
  sqlc.narg(retry_reason)::text,
  NULL,
  0,
  0,
  0,
  '{}'::jsonb,
  '{}'::jsonb,
  now(),
  now()
);

-- name: InsertStep :exec
INSERT INTO step(
  id, round_id, task_id, step_type, dispatch_kind, state, round_index, step_index, depends_on_step_ids, resolved_params, metrics, artifacts,
  input_commit_id, attempt, max_attempts, state_version, created_at, updated_at
) VALUES (
  sqlc.arg(step_id)::uuid,
  sqlc.arg(round_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(step_type)::steptype,
  sqlc.arg(dispatch_kind)::stepdispatchkind,
  'PENDING'::stepstatus,
  sqlc.arg(round_index),
  sqlc.arg(step_index),
  sqlc.arg(depends_on_step_ids)::jsonb,
  sqlc.arg(resolved_params)::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  sqlc.narg(input_commit_id)::uuid,
  1,
  3,
  0,
  now(),
  now()
);

-- name: UpdateLoopAfterRoundCreated :exec
UPDATE loop
SET current_iteration = sqlc.arg(current_iteration),
    phase = sqlc.arg(phase)::loopphase,
    terminal_reason = NULL,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: UpdateLoopPhaseIfRunning :execrows
UPDATE loop
SET phase = sqlc.arg(phase)::loopphase,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid
  AND lifecycle = 'RUNNING'::looplifecycle;

-- name: UpdateLoopLifecycle :exec
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: UpdateLoopLifecycleGuarded :execrows
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid
  AND lifecycle = sqlc.arg(from_lifecycle)::looplifecycle;

-- name: UpdateLoopRuntime :exec
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    phase = sqlc.arg(phase)::loopphase,
    pause_reason = sqlc.narg(pause_reason)::looppausereason,
    terminal_reason = sqlc.narg(terminal_reason)::text,
    last_confirmed_commit_id = sqlc.narg(last_confirmed_commit_id)::uuid,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: UpdateLoopRuntimeGuarded :execrows
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    phase = sqlc.arg(phase)::loopphase,
    pause_reason = sqlc.narg(pause_reason)::looppausereason,
    terminal_reason = sqlc.narg(terminal_reason)::text,
    last_confirmed_commit_id = sqlc.narg(last_confirmed_commit_id)::uuid,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid
  AND lifecycle = sqlc.arg(from_lifecycle)::looplifecycle;

-- name: UpdateLoopPauseStateGuarded :execrows
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    pause_reason = sqlc.narg(pause_reason)::looppausereason,
    terminal_reason = NULL,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid
  AND lifecycle = sqlc.arg(from_lifecycle)::looplifecycle;

-- name: UpdateLoopLastConfirmedCommit :exec
UPDATE loop
SET last_confirmed_commit_id = sqlc.arg(last_confirmed_commit_id)::uuid,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: ListTickLoopIDs :many
SELECT id
FROM loop
WHERE lifecycle IN (
  'RUNNING'::looplifecycle,
  'PAUSING'::looplifecycle,
  'STOPPING'::looplifecycle,
  'FAILED'::looplifecycle
)
ORDER BY updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: CountTaskStatesByRound :many
SELECT
  t.status AS task_status,
  COUNT(*)::int AS count
FROM step s
JOIN task t ON t.id = s.task_id
WHERE s.round_id = sqlc.arg(round_id)::uuid
GROUP BY t.status;

-- name: UpdateRoundAggregate :exec
UPDATE round
SET state = sqlc.arg(state)::roundstatus,
    step_counts = sqlc.arg(step_counts)::jsonb,
    started_at = CASE WHEN sqlc.arg(state)::roundstatus = 'RUNNING'::roundstatus THEN COALESCE(started_at, now()) ELSE started_at END,
    ended_at = CASE WHEN sqlc.arg(state)::roundstatus IN ('COMPLETED'::roundstatus, 'FAILED'::roundstatus, 'CANCELLED'::roundstatus) THEN COALESCE(ended_at, now()) ELSE ended_at END,
    updated_at = now()
WHERE id = sqlc.arg(round_id)::uuid;

-- name: GetRoundState :one
SELECT state
FROM round
WHERE id = sqlc.arg(round_id)::uuid;

-- name: RoundHasStepType :one
SELECT EXISTS (
  SELECT 1
  FROM step
  WHERE round_id = sqlc.arg(round_id)::uuid
    AND step_type = sqlc.arg(step_type)::steptype
)::bool AS exists;

-- name: UpdateRoundStateWithReason :exec
UPDATE round
SET state = sqlc.arg(state)::roundstatus,
    terminal_reason = sqlc.arg(terminal_reason),
    updated_at = now()
WHERE id = sqlc.arg(round_id)::uuid;

-- name: UpdateRoundStateWithReasonGuarded :execrows
UPDATE round
SET state = sqlc.arg(state)::roundstatus,
    terminal_reason = sqlc.arg(terminal_reason),
    updated_at = now()
WHERE id = sqlc.arg(round_id)::uuid
  AND state = sqlc.arg(from_state)::roundstatus;

-- name: MarkRoundConfirmed :execrows
UPDATE round
SET confirmed_at = now(),
    confirmed_revealed_count = sqlc.arg(confirmed_revealed_count),
    confirmed_selected_count = sqlc.arg(confirmed_selected_count),
    confirmed_effective_min_required = sqlc.arg(confirmed_effective_min_required),
    updated_at = now()
WHERE id = sqlc.arg(round_id)::uuid
  AND state = 'COMPLETED'::roundstatus
  AND confirmed_at IS NULL;

-- name: ListRoundActiveStepIDs :many
SELECT s.id AS id
FROM step s
JOIN task t ON t.id = s.task_id
WHERE s.round_id = sqlc.arg(round_id)::uuid
  AND t.status IN (
    'PENDING'::runtimetaskstatus,
    'READY'::runtimetaskstatus,
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus,
    'RUNNING'::runtimetaskstatus,
    'RETRYING'::runtimetaskstatus
  );

-- name: ListLoopStoppableSteps :many
SELECT
  s.id AS id,
  t.id AS task_id,
  t.current_execution_id AS current_execution_id,
  COALESCE(t.assigned_executor_id, '') AS assigned_executor_id,
  t.status AS task_status,
  t.attempt AS attempt,
  t.updated_at AS updated_at
FROM step s
JOIN round j ON j.id = s.round_id
JOIN task t ON t.id = s.task_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.status IN (
    'PENDING'::runtimetaskstatus,
    'READY'::runtimetaskstatus,
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus,
    'RUNNING'::runtimetaskstatus,
    'RETRYING'::runtimetaskstatus
  )
ORDER BY s.created_at ASC;

-- name: GetRuntimeMaintenanceMode :one
SELECT COALESCE(
  (
    SELECT value_json ->> 'value'
    FROM system_setting
    WHERE key = 'maintenance.runtime_mode'
    LIMIT 1
  ),
  'normal'
) AS runtime_mode;

-- name: CountLoopActiveSteps :one
SELECT COUNT(*)::int AS count
FROM step s
JOIN round j ON j.id = s.round_id
JOIN task t ON t.id = s.task_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.status IN (
    'PENDING'::runtimetaskstatus,
    'READY'::runtimetaskstatus,
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus,
    'RUNNING'::runtimetaskstatus,
    'RETRYING'::runtimetaskstatus
  );

-- name: CountLoopInFlightSteps :one
SELECT COUNT(*)::int AS count
FROM step s
JOIN round j ON j.id = s.round_id
JOIN task t ON t.id = s.task_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.status IN (
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus,
    'RUNNING'::runtimetaskstatus,
    'RETRYING'::runtimetaskstatus
  );

-- name: FindRoundIDByStep :one
SELECT round_id
FROM step
WHERE id = sqlc.arg(step_id)::uuid;

-- name: ResolveBranchHeadFromDB :one
SELECT
  head_commit_id,
  project_id
FROM branch
WHERE id = sqlc.arg(branch_id)::uuid;

-- name: CountCommitAnnotationsByCommit :one
SELECT COUNT(*)::bigint AS count
FROM commit_annotation_map
WHERE commit_id = sqlc.arg(commit_id)::uuid;

-- name: GetLoopLifecycle :one
SELECT lifecycle
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetCommandLogByCommandID :one
SELECT
  id,
  status,
  detail
FROM runtime_command_log
WHERE command_id = sqlc.arg(command_id)
LIMIT 1;

-- name: InsertCommandLog :execrows
INSERT INTO runtime_command_log(
  id, command_id, status, detail, created_at, updated_at
) VALUES(
  sqlc.arg(request_id)::uuid,
  sqlc.arg(command_id),
  'accepted',
  'accepted',
  now(),
  now()
)
ON CONFLICT (command_id) DO NOTHING;

-- name: UpdateCommandLogStatusDetail :exec
UPDATE runtime_command_log
SET status = sqlc.arg(status),
    detail = sqlc.arg(detail),
    updated_at = now()
WHERE command_id = sqlc.arg(command_id);
