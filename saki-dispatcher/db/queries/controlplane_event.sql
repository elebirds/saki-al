-- name: InsertStepEvent :execrows
INSERT INTO step_event(id, step_id, seq, ts, event_type, payload, created_at, updated_at)
VALUES(
  sqlc.arg(event_id)::uuid,
  sqlc.arg(step_id)::uuid,
  sqlc.arg(seq),
  sqlc.arg(ts),
  sqlc.arg(event_type),
  sqlc.arg(payload)::jsonb,
  now(),
  now()
)
ON CONFLICT (step_id, seq) DO NOTHING;
