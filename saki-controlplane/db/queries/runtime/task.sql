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

-- name: ClaimPendingTaskForAssignment :one
with candidate as (
    select id
    from runtime_task
    where status = 'pending'
    order by created_at
    for update skip locked
    limit 1
)
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
where id = (select id from candidate);

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

-- name: AssignClaimedTask :one
update runtime_task
set status = 'assigned',
    current_execution_id = sqlc.arg(execution_id),
    assigned_agent_id = sqlc.arg(assigned_agent_id),
    attempt = sqlc.arg(attempt),
    leader_epoch = sqlc.arg(leader_epoch),
    updated_at = now()
where id = sqlc.arg(id)
  and status = 'pending'
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

-- name: RequeueAssignedTasksWithoutAck :execrows
-- recovery 回收未 ack 的 assign 时，必须在同一 SQL 里一起收 task / assignment / command，
-- 否则 task 已回到 pending，但旧 assign command 仍会被 delivery 再次送出。
with stale as (
    select rt.id, rt.current_execution_id, ta.id as assignment_id
    from runtime_task rt
    join task_assignment ta
      on ta.execution_id = rt.current_execution_id
    join agent_command ac
      on ac.assignment_id = ta.id
     and ac.command_type = 'assign'
    where rt.status = 'assigned'
      and ac.acked_at is null
      and ac.created_at <= sqlc.arg(ack_before)
),
expire_commands as (
    update agent_command ac
    set status = 'expired',
        claim_token = null,
        claim_until = null,
        last_error = 'assign_not_acked',
        updated_at = now()
    from stale
    where ac.assignment_id = stale.assignment_id
      and ac.command_type = 'assign'
      and ac.status in ('pending', 'claimed', 'acked')
),
fail_assignments as (
    update task_assignment ta
    set status = 'failed',
        updated_at = now()
    from stale
    where ta.id = stale.assignment_id
)
update runtime_task rt
set status = 'pending',
    current_execution_id = null,
    assigned_agent_id = null,
    leader_epoch = null,
    updated_at = now()
from stale
where rt.id = stale.id;

-- name: FailRunningTasksForOfflineAgents :execrows
-- running 任务的失败也要与 assignment / command 收口绑定在一个原子边界内，
-- 避免 controlplane 一边判定 agent_lost，一边还有旧命令留在可重试状态。
with lost as (
    select rt.id, rt.current_execution_id, ta.id as assignment_id
    from runtime_task rt
    join agent a
      on a.id = rt.assigned_agent_id
    left join task_assignment ta
      on ta.execution_id = rt.current_execution_id
    where rt.status = 'running'
      and a.status = 'offline'
),
fail_assignments as (
    update task_assignment ta
    set status = 'failed',
        updated_at = now()
    from lost
    where ta.id = lost.assignment_id
),
fail_commands as (
    update agent_command ac
    set status = 'failed',
        claim_token = null,
        claim_until = null,
        last_error = 'agent_lost',
        updated_at = now()
    from lost
    where ac.assignment_id = lost.assignment_id
      and ac.status in ('pending', 'claimed', 'acked')
)
update runtime_task rt
set status = 'failed',
    updated_at = now()
from lost
where rt.id = lost.id;

-- name: CancelRequestedTasksForOfflineAgents :execrows
-- cancel_requested 在 agent 已离线时必须直接闭环，
-- 不能只改 task 状态，否则同一 assignment 上旧 assign/cancel command 都可能继续占着 delivery 队列。
with stale as (
    select rt.id, rt.current_execution_id, ta.id as assignment_id
    from runtime_task rt
    join agent a
      on a.id = rt.assigned_agent_id
    left join task_assignment ta
      on ta.execution_id = rt.current_execution_id
    where rt.status = 'cancel_requested'
      and a.status = 'offline'
),
cancel_assignments as (
    update task_assignment ta
    set status = 'canceled',
        updated_at = now()
    from stale
    where ta.id = stale.assignment_id
),
expire_non_cancel_commands as (
    update agent_command ac
    set status = 'expired',
        claim_token = null,
        claim_until = null,
        last_error = 'task_canceled',
        updated_at = now()
    from stale
    where ac.assignment_id = stale.assignment_id
      and ac.command_type <> 'cancel'
      and ac.status in ('pending', 'claimed', 'acked')
),
finish_cancel_commands as (
    update agent_command ac
    set status = 'finished',
        claim_token = null,
        claim_until = null,
        finished_at = now(),
        updated_at = now()
    from stale
    where ac.assignment_id = stale.assignment_id
      and ac.command_type = 'cancel'
      and ac.status in ('pending', 'claimed', 'acked')
)
update runtime_task rt
set status = 'canceled',
    updated_at = now()
from stale
where rt.id = stale.id;
