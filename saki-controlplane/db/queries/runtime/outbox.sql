-- name: AppendRuntimeOutbox :one
insert into runtime_outbox (topic, aggregate_id, payload)
values (sqlc.arg(topic), sqlc.arg(aggregate_id), sqlc.arg(payload))
returning id, topic, aggregate_id, payload, created_at, published_at;
