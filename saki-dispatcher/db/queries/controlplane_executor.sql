-- name: UpsertRuntimeExecutorOnRegister :exec
INSERT INTO runtime_executor(
  id, executor_id, node_id, version, runtime_kind, status, is_online, current_step_id, plugin_ids, resources,
  hardware_profile, mps_stability_profile, kernel_compat_flags, health_status, health_detail, uptime_sec,
  last_seen_at, last_error, created_at, updated_at
) VALUES(
  sqlc.arg(executor_row_id)::uuid,
  sqlc.arg(executor_id),
  sqlc.narg(node_id)::text,
  sqlc.arg(version),
  sqlc.narg(runtime_kind)::text,
  'idle',
  TRUE,
  NULL,
  sqlc.arg(plugin_ids)::jsonb,
  sqlc.arg(resources)::jsonb,
  sqlc.arg(hardware_profile)::jsonb,
  sqlc.arg(mps_stability_profile)::jsonb,
  sqlc.arg(kernel_compat_flags)::jsonb,
  sqlc.arg(health_status),
  sqlc.arg(health_detail)::jsonb,
  sqlc.arg(uptime_sec),
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
  node_id = EXCLUDED.node_id,
  runtime_kind = EXCLUDED.runtime_kind,
  hardware_profile = EXCLUDED.hardware_profile,
  mps_stability_profile = EXCLUDED.mps_stability_profile,
  kernel_compat_flags = EXCLUDED.kernel_compat_flags,
  health_status = EXCLUDED.health_status,
  health_detail = EXCLUDED.health_detail,
  uptime_sec = EXCLUDED.uptime_sec,
  last_seen_at = EXCLUDED.last_seen_at,
  last_error = NULL,
  updated_at = now();

-- name: UpsertRuntimeExecutorOnHeartbeat :exec
INSERT INTO runtime_executor(
  id, executor_id, node_id, version, runtime_kind, status, is_online, current_step_id, plugin_ids, resources,
  hardware_profile, mps_stability_profile, kernel_compat_flags, health_status, health_detail, uptime_sec,
  last_seen_at, last_error, created_at, updated_at
) VALUES(
  sqlc.arg(executor_row_id)::uuid,
  sqlc.arg(executor_id),
  sqlc.narg(node_id)::text,
  '',
  NULL,
  sqlc.arg(status),
  TRUE,
  sqlc.narg(current_step_id)::uuid,
  '{}'::jsonb,
  sqlc.arg(resources)::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  '{}'::jsonb,
  sqlc.arg(health_status),
  sqlc.arg(health_detail)::jsonb,
  sqlc.arg(uptime_sec),
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
  node_id = COALESCE(EXCLUDED.node_id, runtime_executor.node_id),
  health_status = EXCLUDED.health_status,
  health_detail = EXCLUDED.health_detail,
  uptime_sec = EXCLUDED.uptime_sec,
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
