-- name: CreateRuntimeTask :one
insert into runtime_task (id, task_kind, task_type, status)
values (sqlc.arg(id), sqlc.arg(task_kind), sqlc.arg(task_type), 'pending')
returning
    id,
    task_kind,
    task_type,
    status,
    current_execution_id,
    assigned_agent_id,
    attempt,
    max_attempts,
    resolved_params,
    depends_on_task_ids,
    leader_epoch,
    created_at,
    updated_at;

-- name: GetRuntimeTask :one
select
    id,
    task_kind,
    task_type,
    status,
    current_execution_id,
    assigned_agent_id,
    attempt,
    max_attempts,
    resolved_params,
    depends_on_task_ids,
    leader_epoch,
    created_at,
    updated_at
from runtime_task
where id = sqlc.arg(id);

-- name: AssignPendingTask :one
with candidate as (
    select id
    from runtime_task
    where status = 'pending'
    order by created_at
    for update skip locked
    limit 1
)
update runtime_task
set status = 'assigned',
    current_execution_id = encode(gen_random_bytes(16), 'hex'),
    assigned_agent_id = sqlc.arg(assigned_agent_id),
    attempt = runtime_task.attempt + 1,
    leader_epoch = sqlc.arg(leader_epoch),
    updated_at = now()
where id = (select id from candidate)
returning
    id,
    task_kind,
    task_type,
    status,
    current_execution_id,
    assigned_agent_id,
    attempt,
    max_attempts,
    resolved_params,
    depends_on_task_ids,
    leader_epoch,
    created_at,
    updated_at;

-- name: UpdateRuntimeTask :exec
update runtime_task
set status = sqlc.arg(status),
    assigned_agent_id = sqlc.arg(assigned_agent_id),
    leader_epoch = sqlc.arg(leader_epoch),
    updated_at = now()
where id = sqlc.arg(id);

-- name: AdvanceRuntimeTaskByExecution :one
update runtime_task
set status = sqlc.arg(to_status),
    updated_at = now()
where id = sqlc.arg(id)
  and current_execution_id = sqlc.arg(execution_id)
  and status = any(sqlc.arg(from_statuses)::runtime_task_status[])
returning
    id,
    task_kind,
    task_type,
    status,
    current_execution_id,
    assigned_agent_id,
    attempt,
    max_attempts,
    resolved_params,
    depends_on_task_ids,
    leader_epoch,
    created_at,
    updated_at;

-- name: GetRuntimeSummary :one
select
    count(*) filter (where status = 'pending')::integer as pending_tasks,
    count(*) filter (where status in ('assigned', 'running'))::integer as running_tasks,
    coalesce((select max(epoch) from runtime_lease), 0)::bigint as leader_epoch
from runtime_task;
