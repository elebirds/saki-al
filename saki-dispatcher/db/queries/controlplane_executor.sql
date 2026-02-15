-- name: UpsertRuntimeExecutorOnRegister :exec
INSERT INTO runtime_executor(
  id, executor_id, version, status, is_online, current_step_id, plugin_ids, resources, last_seen_at, last_error, created_at, updated_at
) VALUES(
  sqlc.arg(executor_row_id)::uuid,
  sqlc.arg(executor_id),
  sqlc.arg(version),
  'idle',
  TRUE,
  NULL,
  sqlc.arg(plugin_ids)::jsonb,
  sqlc.arg(resources)::jsonb,
  now(),
  NULL,
  now(),
  now()
)
ON CONFLICT (executor_id) DO UPDATE SET
  version = EXCLUDED.version,
  status = 'idle',
  is_online = TRUE,
  current_step_id = NULL,
  plugin_ids = EXCLUDED.plugin_ids,
  resources = EXCLUDED.resources,
  last_seen_at = EXCLUDED.last_seen_at,
  last_error = NULL,
  updated_at = now();

-- name: UpsertRuntimeExecutorOnHeartbeat :exec
INSERT INTO runtime_executor(
  id, executor_id, version, status, is_online, current_step_id, plugin_ids, resources, last_seen_at, last_error, created_at, updated_at
) VALUES(
  sqlc.arg(executor_row_id)::uuid,
  sqlc.arg(executor_id),
  '',
  sqlc.arg(status),
  TRUE,
  sqlc.narg(current_step_id)::text,
  '{}'::jsonb,
  sqlc.arg(resources)::jsonb,
  now(),
  NULL,
  now(),
  now()
)
ON CONFLICT (executor_id) DO UPDATE SET
  status = EXCLUDED.status,
  is_online = TRUE,
  current_step_id = EXCLUDED.current_step_id,
  resources = EXCLUDED.resources,
  last_seen_at = EXCLUDED.last_seen_at,
  last_error = NULL,
  updated_at = now();

-- name: UpdateRuntimeExecutorDisconnected :exec
UPDATE runtime_executor
SET status = 'offline',
    is_online = FALSE,
    current_step_id = NULL,
    last_error = sqlc.narg(reason)::text,
    last_seen_at = now(),
    updated_at = now()
WHERE executor_id = sqlc.arg(executor_id);
