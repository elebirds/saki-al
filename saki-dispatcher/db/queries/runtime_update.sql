-- name: ListRuntimeDesiredReleases :many
SELECT
  ds.component_type,
  ds.component_name,
  ds.release_id,
  r.version,
  r.asset_id,
  r.sha256,
  r.size_bytes,
  r.format,
  COALESCE(r.manifest_json, '{}'::jsonb) AS manifest_json
FROM runtime_desired_state ds
JOIN runtime_release r ON r.id = ds.release_id
ORDER BY ds.component_type ASC, ds.component_name ASC;

-- name: InsertRuntimeUpdateAttempt :execrows
INSERT INTO runtime_update_attempt(
  id,
  executor_id,
  component_type,
  component_name,
  request_id,
  from_version,
  target_version,
  status,
  detail,
  started_at,
  ended_at,
  rolled_back,
  rollback_detail,
  created_at,
  updated_at
) VALUES(
  sqlc.arg(id)::uuid,
  sqlc.arg(executor_id),
  sqlc.arg(component_type),
  sqlc.arg(component_name),
  sqlc.arg(request_id),
  sqlc.arg(from_version),
  sqlc.arg(target_version),
  sqlc.arg(status),
  sqlc.narg(detail),
  sqlc.narg(started_at),
  sqlc.narg(ended_at),
  sqlc.arg(rolled_back),
  sqlc.narg(rollback_detail),
  now(),
  now()
)
ON CONFLICT (request_id) DO NOTHING;

-- name: UpdateRuntimeUpdateAttemptByRequestID :execrows
UPDATE runtime_update_attempt
SET
  status = sqlc.arg(status),
  detail = sqlc.narg(detail),
  ended_at = sqlc.narg(ended_at),
  rolled_back = sqlc.arg(rolled_back),
  rollback_detail = sqlc.narg(rollback_detail),
  updated_at = now()
WHERE request_id = sqlc.arg(request_id);
