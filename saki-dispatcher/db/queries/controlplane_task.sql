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
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: PromoteTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    last_error = NULL,
    ended_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'PENDING'::runtimetaskstatus;

-- name: PromoteRetryingTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    last_error = NULL,
    ended_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'RETRYING'::runtimetaskstatus;

-- name: MarkTaskDispatchingFromReady :execrows
UPDATE task
SET status = 'DISPATCHING'::runtimetaskstatus,
    assigned_executor_id = sqlc.arg(assigned_executor_id),
    last_error = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status = 'READY'::runtimetaskstatus;

-- name: ResetTaskToReadyQueueFull :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    last_error = 'executor unavailable or queue full',
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
    last_error = sqlc.narg(last_error)::text,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: MarkOrchestratorTaskRunning :execrows
UPDATE task
SET status = 'RUNNING'::runtimetaskstatus,
    started_at = COALESCE(started_at, now()),
    last_error = NULL,
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
    last_error = sqlc.narg(last_error)::text,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: CancelTaskByID :execrows
UPDATE task
SET status = 'CANCELLED'::runtimetaskstatus,
    last_error = sqlc.arg(last_error),
    ended_at = COALESCE(ended_at, now()),
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: RecoverStaleDispatchingTaskToReady :execrows
UPDATE task
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    last_error = sqlc.arg(last_error),
    ended_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid
  AND status IN (
    'DISPATCHING'::runtimetaskstatus,
    'SYNCING_ENV'::runtimetaskstatus,
    'PROBING_RUNTIME'::runtimetaskstatus,
    'BINDING_DEVICE'::runtimetaskstatus
  );

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
