-- name: InsertTaskEvent :execrows
INSERT INTO task_event(id, task_id, execution_id, seq, ts, event_type, payload, created_at, updated_at)
VALUES(
  sqlc.arg(event_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(execution_id)::uuid,
  sqlc.arg(seq),
  sqlc.arg(ts),
  sqlc.arg(event_type),
  sqlc.arg(payload)::jsonb,
  now(),
  now()
)
ON CONFLICT (task_id, execution_id, seq) DO NOTHING;

-- name: InsertTaskStatusSystemEvent :execrows
INSERT INTO task_event(id, task_id, execution_id, seq, ts, event_type, payload, created_at, updated_at)
SELECT
  sqlc.arg(event_id)::uuid,
  sqlc.arg(task_id)::uuid,
  t.current_execution_id,
  COALESCE((
    SELECT MAX(e.seq) + 1
    FROM task_event e
    WHERE e.task_id = sqlc.arg(task_id)::uuid
      AND e.execution_id = t.current_execution_id
  ), 1),
  sqlc.arg(ts),
  'status',
  sqlc.arg(payload)::jsonb,
  now(),
  now()
FROM task t
WHERE t.id = sqlc.arg(task_id)::uuid
ON CONFLICT (task_id, execution_id, seq) DO NOTHING;
