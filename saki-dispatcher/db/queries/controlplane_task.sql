-- name: GetStepIDByTaskID :one
SELECT id
FROM step
WHERE task_id = sqlc.arg(task_id)::uuid
LIMIT 1;

-- name: GetTaskIDByStepID :one
SELECT task_id
FROM step
WHERE id = sqlc.arg(step_id)::uuid;

-- name: InsertStepTask :exec
INSERT INTO task(
  created_at,
  updated_at,
  id,
  project_id,
  kind,
  task_type,
  status,
  plugin_id,
  depends_on_task_ids,
  input_commit_id,
  resolved_params,
  assigned_executor_id,
  attempt,
  max_attempts,
  started_at,
  ended_at,
  last_error
) VALUES (
  now(),
  now(),
  sqlc.arg(task_id)::uuid,
  sqlc.arg(project_id)::uuid,
  'STEP'::runtimetaskkind,
  sqlc.arg(task_type)::runtimetasktype,
  'PENDING'::runtimetaskstatus,
  sqlc.arg(plugin_id),
  sqlc.arg(depends_on_task_ids)::jsonb,
  sqlc.narg(input_commit_id)::uuid,
  sqlc.arg(resolved_params)::jsonb,
  NULL,
  1,
  sqlc.arg(max_attempts),
  NULL,
  NULL,
  NULL
);

-- name: DeleteTaskByID :execrows
DELETE FROM task
WHERE id = sqlc.arg(task_id)::uuid;

-- name: GetTaskForUpdate :one
SELECT
  id,
  project_id,
  kind::text AS kind,
  task_type::text AS task_type,
  status::text AS status,
  plugin_id,
  input_commit_id,
  COALESCE(resolved_params, '{}'::jsonb) AS resolved_params_json,
  attempt,
  max_attempts,
  COALESCE(assigned_executor_id, '') AS assigned_executor_id,
  COALESCE(last_error, '') AS last_error
FROM task
WHERE id = sqlc.arg(task_id)::uuid
FOR UPDATE;

-- name: MarkTaskDispatching :execrows
UPDATE task
SET status = 'DISPATCHING'::runtimetaskstatus,
    assigned_executor_id = sqlc.arg(assigned_executor_id),
    last_error = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: PromoteTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    last_error = NULL,
    ended_at = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'PENDING'::runtimetaskstatus;

-- name: PromoteRetryingTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    last_error = NULL,
    ended_at = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'RETRYING'::runtimetaskstatus;

-- name: MarkTaskDispatchingFromReady :execrows
UPDATE task
SET status = 'DISPATCHING'::runtimetaskstatus,
    assigned_executor_id = sqlc.arg(assigned_executor_id),
    last_error = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'READY'::runtimetaskstatus;

-- name: ResetTaskToReadyQueueFull :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    last_error = 'executor unavailable or queue full',
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: UpdateTaskStatusLifecycle :execrows
UPDATE task
SET status = sqlc.arg(status)::runtimetaskstatus,
    started_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'RUNNING'::runtimetaskstatus,
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(started_at, now())
      ELSE started_at
    END,
    ended_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(ended_at, now())
      ELSE ended_at
    END,
    result_ready_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'PENDING'::runtimetaskstatus,
        'READY'::runtimetaskstatus,
        'DISPATCHING'::runtimetaskstatus,
        'SYNCING_ENV'::runtimetaskstatus,
        'PROBING_RUNTIME'::runtimetaskstatus,
        'BINDING_DEVICE'::runtimetaskstatus,
        'RUNNING'::runtimetaskstatus,
        'RETRYING'::runtimetaskstatus
      ) THEN NULL
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN NULL
      ELSE result_ready_at
    END,
    last_error = sqlc.narg(last_error)::text,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: MarkOrchestratorTaskRunning :execrows
UPDATE task
SET status = 'RUNNING'::runtimetaskstatus,
    started_at = COALESCE(started_at, now()),
    last_error = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'READY'::runtimetaskstatus;

-- name: MarkOrchestratorTaskRetrying :execrows
UPDATE task
SET status = 'RETRYING'::runtimetaskstatus,
    attempt = attempt + 1,
    last_error = sqlc.arg(last_error),
    assigned_executor_id = NULL,
    ended_at = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'RUNNING'::runtimetaskstatus
  AND attempt < max_attempts;

-- name: UpdateTaskExecutionResultGuarded :execrows
UPDATE task
SET status = sqlc.arg(status)::runtimetaskstatus,
    started_at = COALESCE(started_at, now()),
    ended_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(ended_at, now())
      ELSE ended_at
    END,
    last_error = sqlc.narg(last_error)::text,
    assigned_executor_id = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus,
        'RETRYING'::runtimetaskstatus
      ) THEN NULL
      ELSE assigned_executor_id
    END,
    result_ready_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus = 'SUCCEEDED'::runtimetaskstatus THEN COALESCE(result_ready_at, now())
      ELSE NULL
    END,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = sqlc.arg(from_status)::runtimetaskstatus;

-- name: UpdateTaskResult :execrows
UPDATE task
SET status = sqlc.arg(status)::runtimetaskstatus,
    resolved_params = sqlc.arg(resolved_params)::jsonb,
    started_at = COALESCE(started_at, now()),
    ended_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus IN (
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(ended_at, now())
      ELSE ended_at
    END,
    result_ready_at = CASE
      WHEN sqlc.arg(status)::runtimetaskstatus = 'SUCCEEDED'::runtimetaskstatus THEN COALESCE(result_ready_at, now())
      ELSE NULL
    END,
    last_error = sqlc.narg(last_error)::text,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: CancelTaskByID :execrows
UPDATE task
SET status = 'CANCELLED'::runtimetaskstatus,
    last_error = sqlc.arg(last_error),
    ended_at = COALESCE(ended_at, now()),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: RecoverStaleDispatchingTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    last_error = sqlc.arg(last_error),
    ended_at = NULL,
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status IN (
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus
  );

-- name: ResetDispatchingTaskToReadyByAck :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    ended_at = NULL,
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'DISPATCHING'::runtimetaskstatus
  AND assigned_executor_id = sqlc.arg(assigned_executor_id);

-- name: RetryDispatchingTaskByAck :execrows
UPDATE task
SET status = 'RETRYING'::runtimetaskstatus,
    attempt = attempt + 1,
    assigned_executor_id = NULL,
    ended_at = NULL,
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'DISPATCHING'::runtimetaskstatus
  AND assigned_executor_id = sqlc.arg(assigned_executor_id)
  AND attempt < max_attempts;

-- name: FailDispatchingTaskByAck :execrows
UPDATE task
SET status = 'FAILED'::runtimetaskstatus,
    assigned_executor_id = NULL,
    started_at = COALESCE(started_at, now()),
    ended_at = COALESCE(ended_at, now()),
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'DISPATCHING'::runtimetaskstatus
  AND assigned_executor_id = sqlc.arg(assigned_executor_id);

-- name: RecoverPreRunTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    ended_at = NULL,
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status IN (
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus
  )
  AND (
    sqlc.arg(assigned_executor_id) = ''
    OR assigned_executor_id = sqlc.arg(assigned_executor_id)
  );

-- name: RecoverRunningTaskToRetrying :execrows
UPDATE task
SET status = 'RETRYING'::runtimetaskstatus,
    attempt = attempt + 1,
    assigned_executor_id = NULL,
    ended_at = NULL,
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'RUNNING'::runtimetaskstatus
  AND attempt < max_attempts
  AND (
    sqlc.arg(assigned_executor_id) = ''
    OR assigned_executor_id = sqlc.arg(assigned_executor_id)
  );

-- name: RecoverRunningTaskToFailed :execrows
UPDATE task
SET status = 'FAILED'::runtimetaskstatus,
    assigned_executor_id = NULL,
    started_at = COALESCE(started_at, now()),
    ended_at = COALESCE(ended_at, now()),
    last_error = sqlc.arg(last_error),
    result_ready_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'RUNNING'::runtimetaskstatus
  AND (
    sqlc.arg(assigned_executor_id) = ''
    OR assigned_executor_id = sqlc.arg(assigned_executor_id)
  );

-- name: ListInFlightTaskRecoveryCandidates :many
SELECT
  t.id AS task_id,
  t.kind::text AS task_kind,
  t.status AS task_status,
  t.attempt AS attempt,
  t.max_attempts AS max_attempts,
  COALESCE(t.assigned_executor_id, '') AS assigned_executor_id,
  t.updated_at AS task_updated_at,
  COALESCE(r.is_online, FALSE) AS executor_online,
  r.last_seen_at AS executor_last_seen_at,
  COALESCE(r.current_task_id, '') AS executor_current_task_id
FROM task t
LEFT JOIN runtime_executor r ON r.executor_id = t.assigned_executor_id
WHERE t.status IN (
  'DISPATCHING'::runtimetaskstatus,
  'SYNCING_ENV'::runtimetaskstatus,
  'PROBING_RUNTIME'::runtimetaskstatus,
  'BINDING_DEVICE'::runtimetaskstatus,
  'RUNNING'::runtimetaskstatus
)
ORDER BY t.updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: ListInFlightTaskIDsByExecutor :many
SELECT id
FROM task
WHERE assigned_executor_id = sqlc.arg(executor_id)
  AND status IN (
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus,
    'RUNNING'::runtimetaskstatus
  )
ORDER BY updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: ProjectStepFromTask :execrows
UPDATE step s
SET state = t.status::text::stepstatus,
    state_version = CASE
      WHEN s.state IS DISTINCT FROM t.status::text::stepstatus THEN s.state_version + 1
      ELSE s.state_version
    END,
    attempt = t.attempt,
    max_attempts = t.max_attempts,
    assigned_executor_id = t.assigned_executor_id,
    started_at = CASE
      WHEN t.status IN (
        'RUNNING'::runtimetaskstatus,
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(s.started_at, t.started_at, now())
      ELSE s.started_at
    END,
    ended_at = CASE
      WHEN t.status IN (
        'SUCCEEDED'::runtimetaskstatus,
        'FAILED'::runtimetaskstatus,
        'CANCELLED'::runtimetaskstatus,
        'SKIPPED'::runtimetaskstatus
      ) THEN COALESCE(s.ended_at, t.ended_at, now())
      ELSE s.ended_at
    END,
    last_error = t.last_error,
    updated_at = now()
FROM task t
WHERE t.id = sqlc.arg(task_id)::uuid
  AND s.task_id = t.id;
