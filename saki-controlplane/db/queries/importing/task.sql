-- name: CreateImportTask :one
insert into import_task (
    id,
    user_id,
    mode,
    resource_type,
    resource_id,
    status,
    payload,
    result
)
values (
    sqlc.arg(id),
    sqlc.arg(user_id),
    sqlc.arg(mode),
    sqlc.arg(resource_type),
    sqlc.arg(resource_id),
    'queued',
    sqlc.arg(payload),
    '{}'::jsonb
)
returning id, user_id, mode, resource_type, resource_id, status, payload, result, created_at, updated_at;

-- name: GetImportTask :one
select id, user_id, mode, resource_type, resource_id, status, payload, result, created_at, updated_at
from import_task
where id = sqlc.arg(id);

-- name: AppendImportTaskEvent :one
insert into import_task_event (
    task_id,
    event,
    phase,
    payload
)
values (
    sqlc.arg(task_id),
    sqlc.arg(event),
    sqlc.arg(phase),
    sqlc.arg(payload)
)
returning seq, task_id, event, phase, payload, created_at;

-- name: ListImportTaskEventsAfter :many
select seq, task_id, event, phase, payload, created_at
from import_task_event
where task_id = sqlc.arg(task_id)
  and seq > sqlc.arg(after_seq)
order by seq
limit sqlc.arg(limit_count);
