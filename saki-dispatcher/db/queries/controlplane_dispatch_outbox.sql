-- name: InsertDispatchOutbox :execrows
INSERT INTO task_dispatch_outbox(
  id,
  task_id,
  executor_id,
  request_id,
  payload,
  status,
  attempt_count,
  next_attempt_at,
  created_at,
  updated_at
) VALUES (
  sqlc.arg(outbox_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(executor_id),
  sqlc.arg(request_id),
  sqlc.arg(payload)::jsonb,
  'PENDING',
  0,
  now(),
  now(),
  now()
)
ON CONFLICT (request_id) DO NOTHING;

-- name: ClaimDispatchOutboxDue :many
WITH picked AS (
  SELECT id
  FROM task_dispatch_outbox
  WHERE status = 'PENDING'
    AND next_attempt_at <= now()
  ORDER BY next_attempt_at ASC, created_at ASC
  LIMIT sqlc.arg(limit_count)
  FOR UPDATE SKIP LOCKED
)
UPDATE task_dispatch_outbox o
SET status = 'SENDING',
    locked_at = now(),
    attempt_count = o.attempt_count + 1,
    updated_at = now()
FROM picked
WHERE o.id = picked.id
RETURNING
  o.id AS id,
  o.task_id AS task_id,
  o.executor_id,
  o.request_id,
  o.payload,
  o.attempt_count;

-- name: MarkDispatchOutboxSent :execrows
UPDATE task_dispatch_outbox
SET status = 'SENT',
    sent_at = now(),
    locked_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(outbox_id)::uuid
  AND status = 'SENDING';

-- name: MarkDispatchOutboxRetry :execrows
UPDATE task_dispatch_outbox
SET status = 'PENDING',
    next_attempt_at = sqlc.arg(next_attempt_at),
    last_error = sqlc.narg(last_error)::text,
    locked_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(outbox_id)::uuid
  AND status = 'SENDING';

-- name: ReleaseStaleSendingOutbox :execrows
UPDATE task_dispatch_outbox
SET status = 'PENDING',
    next_attempt_at = now(),
    last_error = 'stale sending lock released',
    locked_at = NULL,
    updated_at = now()
WHERE status = 'SENDING'
  AND locked_at IS NOT NULL
  AND locked_at < sqlc.arg(cutoff);

-- name: DeleteDispatchOutboxForTerminalTasks :execrows
DELETE FROM task_dispatch_outbox o
USING task t
WHERE o.task_id = t.id
  AND o.status IN ('PENDING', 'SENDING')
  AND t.status IN (
    'SUCCEEDED'::runtimetaskstatus,
    'FAILED'::runtimetaskstatus,
    'CANCELLED'::runtimetaskstatus,
    'SKIPPED'::runtimetaskstatus
  );

-- name: DeleteDispatchOutboxByID :execrows
DELETE FROM task_dispatch_outbox
WHERE id = sqlc.arg(outbox_id)::uuid;

-- name: ListActiveDispatchOutboxRecoveryCandidates :many
SELECT
  o.id AS id,
  o.task_id AS task_id,
  o.executor_id,
  o.request_id,
  o.status::text AS outbox_status,
  o.attempt_count,
  COALESCE(o.last_error, '') AS last_error,
  COALESCE(o.payload->>'executionId', '') AS payload_execution_id,
  o.created_at,
  o.updated_at,
  t.kind::text AS task_kind,
  t.status::text AS task_status,
  COALESCE(t.plugin_id, '') AS plugin_id,
  t.current_execution_id,
  COALESCE(t.assigned_executor_id, '') AS assigned_executor_id,
  COALESCE(r.is_online, FALSE) AS executor_online,
  COALESCE(r.status, '') AS executor_status
FROM task_dispatch_outbox o
JOIN task t ON t.id = o.task_id
LEFT JOIN runtime_executor r ON r.executor_id = o.executor_id
WHERE o.status IN ('PENDING', 'SENDING')
ORDER BY
  o.task_id ASC,
  o.updated_at DESC,
  o.created_at DESC,
  o.id DESC
LIMIT sqlc.arg(limit_count);

-- name: ListOrphanDispatchingTaskIDs :many
SELECT t.id AS id
FROM task t
WHERE t.status IN (
  'DISPATCHING'::runtimetaskstatus,
  'SYNCING_ENV'::runtimetaskstatus,
  'PROBING_RUNTIME'::runtimetaskstatus,
  'BINDING_DEVICE'::runtimetaskstatus
)
  AND t.updated_at < sqlc.arg(cutoff)
  AND NOT EXISTS (
    SELECT 1
    FROM task_dispatch_outbox o
    WHERE o.task_id = t.id
      AND o.status IN ('PENDING', 'SENDING')
  )
ORDER BY t.updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: DeleteSentDispatchOutboxBefore :execrows
DELETE FROM task_dispatch_outbox
WHERE status = 'SENT'
  AND sent_at IS NOT NULL
  AND sent_at < sqlc.arg(cutoff);
