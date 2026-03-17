-- name: AppendRuntimeOutbox :one
insert into runtime_outbox (
    topic,
    aggregate_type,
    aggregate_id,
    idempotency_key,
    payload,
    available_at
)
values (
    sqlc.arg(topic),
    sqlc.arg(aggregate_type),
    sqlc.arg(aggregate_id),
    sqlc.arg(idempotency_key),
    sqlc.arg(payload),
    sqlc.arg(available_at)
)
returning
    id,
    topic,
    aggregate_type,
    aggregate_id,
    idempotency_key,
    payload,
    available_at,
    attempt_count,
    created_at,
    published_at,
    last_error;

-- name: ClaimDueRuntimeOutbox :many
with due as (
    select id
    from runtime_outbox
    where published_at is null
      and available_at <= now()
    order by available_at, id
    for update skip locked
    limit sqlc.arg(limit_count)
)
update runtime_outbox
set available_at = sqlc.arg(claim_until),
    attempt_count = runtime_outbox.attempt_count + 1,
    last_error = null
from due
where runtime_outbox.id = due.id
returning
    runtime_outbox.id,
    runtime_outbox.topic,
    runtime_outbox.aggregate_type,
    runtime_outbox.aggregate_id,
    runtime_outbox.idempotency_key,
    runtime_outbox.payload,
    runtime_outbox.available_at,
    runtime_outbox.attempt_count,
    runtime_outbox.created_at,
    runtime_outbox.published_at,
    runtime_outbox.last_error;

-- name: MarkRuntimeOutboxPublished :exec
update runtime_outbox
set published_at = now(),
    last_error = null
where id = sqlc.arg(id);

-- name: MarkRuntimeOutboxRetry :exec
update runtime_outbox
set available_at = sqlc.arg(next_available_at),
    last_error = sqlc.arg(last_error)
where id = sqlc.arg(id);
