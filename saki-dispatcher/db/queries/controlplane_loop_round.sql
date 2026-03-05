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
  last_confirmed_commit_id
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
  last_confirmed_commit_id
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
  id, round_id, step_type, dispatch_kind, state, round_index, step_index, depends_on_step_ids, resolved_params, metrics, artifacts,
  input_commit_id, attempt, max_attempts, state_version, created_at, updated_at
) VALUES (
  sqlc.arg(step_id)::uuid,
  sqlc.arg(round_id)::uuid,
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
    terminal_reason = sqlc.narg(terminal_reason)::text,
    last_confirmed_commit_id = sqlc.narg(last_confirmed_commit_id)::uuid,
    updated_at = now()
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: UpdateLoopRuntimeGuarded :execrows
UPDATE loop
SET lifecycle = sqlc.arg(lifecycle)::looplifecycle,
    phase = sqlc.arg(phase)::loopphase,
    terminal_reason = sqlc.narg(terminal_reason)::text,
    last_confirmed_commit_id = sqlc.narg(last_confirmed_commit_id)::uuid,
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
WHERE lifecycle IN ('RUNNING'::looplifecycle, 'STOPPING'::looplifecycle)
ORDER BY updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: CountStepStatesByRound :many
SELECT state, COUNT(*)::int AS count
FROM step
WHERE round_id = sqlc.arg(round_id)::uuid
GROUP BY state;

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
SELECT id
FROM step
WHERE round_id = sqlc.arg(round_id)::uuid
  AND state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  );

-- name: CancelStepsByRound :exec
UPDATE step
SET state = 'CANCELLED'::stepstatus,
    last_error = sqlc.arg(last_error),
    ended_at = COALESCE(ended_at, now()),
    state_version = state_version + 1,
    updated_at = now()
WHERE round_id = sqlc.arg(round_id)::uuid
  AND state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  );

-- name: GetStepState :one
SELECT state
FROM step
WHERE id = sqlc.arg(step_id)::uuid;

-- name: CancelStepByID :exec
UPDATE step
SET state = 'CANCELLED'::stepstatus,
    last_error = sqlc.arg(last_error),
    ended_at = COALESCE(ended_at, now()),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid
  AND state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  );

-- name: ListLoopStoppableSteps :many
SELECT
  t.id AS id,
  t.state,
  t.attempt,
  t.updated_at
FROM step t
JOIN round j ON j.id = t.round_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  )
ORDER BY t.created_at ASC;

-- name: CancelStepsByIDs :exec
UPDATE step
SET state = 'CANCELLED'::stepstatus,
    last_error = sqlc.arg(last_error),
    ended_at = COALESCE(ended_at, now()),
    state_version = state_version + 1,
    updated_at = now()
WHERE id = ANY(sqlc.arg(step_ids)::uuid[])
  AND state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  );

-- name: CountLoopActiveSteps :one
SELECT COUNT(*)::int AS count
FROM step t
JOIN round j ON j.id = t.round_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.state IN (
    'PENDING'::stepstatus,
    'READY'::stepstatus,
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
  );

-- name: CountLoopInFlightSteps :one
SELECT COUNT(*)::int AS count
FROM step t
JOIN round j ON j.id = t.round_id
WHERE j.loop_id = sqlc.arg(loop_id)::uuid
  AND t.state IN (
    'DISPATCHING'::stepstatus,
    'SYNCING_ENV'::stepstatus,
    'PROBING_RUNTIME'::stepstatus,
    'BINDING_DEVICE'::stepstatus,
    'RUNNING'::stepstatus,
    'RETRYING'::stepstatus
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
