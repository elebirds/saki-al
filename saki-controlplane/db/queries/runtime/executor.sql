-- name: RegisterRuntimeExecutor :one
insert into runtime_executor (id, version, capabilities, status, last_seen_at)
values (
    sqlc.arg(id),
    sqlc.arg(version),
    sqlc.arg(capabilities)::text[],
    'online',
    sqlc.arg(last_seen_at)
)
on conflict (id) do update
set version = excluded.version,
    capabilities = excluded.capabilities,
    status = 'online',
    last_seen_at = excluded.last_seen_at,
    updated_at = now()
returning id, version, capabilities, status, last_seen_at, created_at, updated_at;

-- name: HeartbeatRuntimeExecutor :one
update runtime_executor
set last_seen_at = sqlc.arg(last_seen_at),
    status = 'online',
    updated_at = now()
where id = sqlc.arg(id)
returning id, version, capabilities, status, last_seen_at, created_at, updated_at;

-- name: ListRuntimeExecutors :many
select id, version, capabilities, status, last_seen_at, created_at, updated_at
from runtime_executor
order by id;
