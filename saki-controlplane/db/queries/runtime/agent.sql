-- name: UpsertAgent :one
insert into agent (
    id,
    version,
    capabilities,
    transport_mode,
    control_base_url,
    max_concurrency,
    running_task_ids,
    status,
    last_seen_at
)
values (
    sqlc.arg(id),
    sqlc.arg(version),
    sqlc.arg(capabilities)::text[],
    sqlc.arg(transport_mode),
    sqlc.narg(control_base_url),
    sqlc.arg(max_concurrency),
    sqlc.arg(running_task_ids)::text[],
    'online',
    sqlc.arg(last_seen_at)
)
on conflict (id) do update
set version = excluded.version,
    capabilities = excluded.capabilities,
    transport_mode = excluded.transport_mode,
    control_base_url = excluded.control_base_url,
    max_concurrency = excluded.max_concurrency,
    running_task_ids = excluded.running_task_ids,
    status = 'online',
    last_seen_at = excluded.last_seen_at,
    updated_at = now()
returning
    id,
    version,
    capabilities,
    transport_mode,
    control_base_url,
    max_concurrency,
    running_task_ids,
    status,
    last_seen_at,
    created_at,
    updated_at;

-- name: HeartbeatAgent :one
update agent
set version = coalesce(nullif(sqlc.arg(version), ''), version),
    max_concurrency = sqlc.arg(max_concurrency),
    running_task_ids = sqlc.arg(running_task_ids)::text[],
    status = 'online',
    last_seen_at = sqlc.arg(last_seen_at),
    updated_at = now()
where id = sqlc.arg(id)
returning
    id,
    version,
    capabilities,
    transport_mode,
    control_base_url,
    max_concurrency,
    running_task_ids,
    status,
    last_seen_at,
    created_at,
    updated_at;

-- name: ListAgents :many
select
    id,
    version,
    capabilities,
    transport_mode,
    control_base_url,
    max_concurrency,
    running_task_ids,
    status,
    last_seen_at,
    created_at,
    updated_at
from agent
order by id;

-- name: GetAgentByID :one
select
    id,
    version,
    capabilities,
    transport_mode,
    control_base_url,
    max_concurrency,
    running_task_ids,
    status,
    last_seen_at,
    created_at,
    updated_at
from agent
where id = sqlc.arg(id);

-- name: MarkOfflineAgentsBefore :execrows
-- recovery 先固化离线事实，再由后续 SQL 基于 offline 状态收 task / assignment / command。
update agent
set status = 'offline',
    updated_at = now()
where last_seen_at <= sqlc.arg(offline_before)
  and status <> 'offline';
