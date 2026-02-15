-- name: InsertStepEvent :execrows
INSERT INTO step_event(id, step_id, seq, ts, event_type, payload, request_id, created_at, updated_at)
VALUES(
  sqlc.arg(event_id)::uuid,
  sqlc.arg(step_id)::uuid,
  sqlc.arg(seq),
  sqlc.arg(ts),
  sqlc.arg(event_type),
  sqlc.arg(payload)::jsonb,
  sqlc.narg(request_id)::text,
  now(),
  now()
)
ON CONFLICT (step_id, seq) DO NOTHING;
