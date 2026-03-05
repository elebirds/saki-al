-- name: InsertStepEvent :execrows
INSERT INTO task_event(id, task_id, seq, ts, event_type, payload, created_at, updated_at)
VALUES(
  sqlc.arg(event_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(seq),
  sqlc.arg(ts),
  sqlc.arg(event_type),
  sqlc.arg(payload)::jsonb,
  now(),
  now()
)
ON CONFLICT (task_id, seq) DO NOTHING;
