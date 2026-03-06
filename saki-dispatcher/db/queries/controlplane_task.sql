-- name: GetStepIDByTaskID :one
SELECT id
FROM step
WHERE task_id = sqlc.arg(task_id)::uuid
LIMIT 1;

-- name: GetTaskIDByStepID :one
SELECT task_id
FROM step
WHERE id = sqlc.arg(step_id)::uuid;

-- name: ListStepTaskBindingsByStepIDs :many
SELECT
  id AS step_id,
  task_id
FROM step
WHERE id = ANY(sqlc.arg(step_ids)::uuid[]);

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
  sqlc.narg(input_commit_id)::uuid,
  sqlc.arg(resolved_params)::jsonb,
  NULL,
  1,
  sqlc.arg(max_attempts),
  NULL,
  NULL,
  NULL
);

-- name: BindTaskToStep :execrows
UPDATE step
SET task_id = sqlc.arg(task_id)::uuid
WHERE id = sqlc.arg(step_id)::uuid;

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

-- name: SetTaskAssignedExecutor :execrows
UPDATE task
SET assigned_executor_id = sqlc.arg(assigned_executor_id),
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

-- name: ClearTaskAssignedExecutor :execrows
UPDATE task
SET assigned_executor_id = NULL,
    updated_at = now()
WHERE id = sqlc.arg(task_id)::uuid;

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
