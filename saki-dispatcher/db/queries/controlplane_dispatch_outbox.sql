-- name: InsertDispatchOutbox :execrows
INSERT INTO dispatch_outbox(
  id,
  step_id,
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
  sqlc.arg(step_id)::uuid,
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
  FROM dispatch_outbox
  WHERE status = 'PENDING'
    AND next_attempt_at <= now()
  ORDER BY next_attempt_at ASC, created_at ASC
  LIMIT sqlc.arg(limit_count)
  FOR UPDATE SKIP LOCKED
)
UPDATE dispatch_outbox o
SET status = 'SENDING',
    locked_at = now(),
    attempt_count = o.attempt_count + 1,
    updated_at = now()
FROM picked
WHERE o.id = picked.id
RETURNING
  o.id AS id,
  o.step_id AS step_id,
  o.executor_id,
  o.request_id,
  o.payload,
  o.attempt_count;

-- name: MarkDispatchOutboxSent :execrows
UPDATE dispatch_outbox
SET status = 'SENT',
    sent_at = now(),
    locked_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(outbox_id)::uuid
  AND status = 'SENDING';

-- name: MarkDispatchOutboxRetry :execrows
UPDATE dispatch_outbox
SET status = 'PENDING',
    next_attempt_at = sqlc.arg(next_attempt_at),
    last_error = sqlc.narg(last_error)::text,
    locked_at = NULL,
    updated_at = now()
WHERE id = sqlc.arg(outbox_id)::uuid
  AND status = 'SENDING';

-- name: ReleaseStaleSendingOutbox :execrows
UPDATE dispatch_outbox
SET status = 'PENDING',
    next_attempt_at = now(),
    last_error = 'stale sending lock released',
    locked_at = NULL,
    updated_at = now()
WHERE status = 'SENDING'
  AND locked_at IS NOT NULL
  AND locked_at < sqlc.arg(cutoff);

-- name: ListOrphanDispatchingStepIDs :many
SELECT s.id AS id
FROM step s
WHERE s.state = 'DISPATCHING'::stepstatus
  AND s.updated_at < sqlc.arg(cutoff)
  AND NOT EXISTS (
    SELECT 1
    FROM dispatch_outbox o
    WHERE o.step_id = s.id
      AND o.status IN ('PENDING', 'SENDING')
  )
ORDER BY s.updated_at ASC
LIMIT sqlc.arg(limit_count);

-- name: DeleteSentDispatchOutboxBefore :execrows
DELETE FROM dispatch_outbox
WHERE status = 'SENT'
  AND sent_at IS NOT NULL
  AND sent_at < sqlc.arg(cutoff);
