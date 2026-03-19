-- name: AppendAgentCommand :one
insert into agent_command (
    command_id,
    agent_id,
    task_id,
    assignment_id,
    command_type,
    transport_mode,
    status,
    payload,
    available_at,
    expire_at
)
values (
    sqlc.arg(command_id),
    sqlc.arg(agent_id),
    sqlc.arg(task_id),
    sqlc.arg(assignment_id),
    sqlc.arg(command_type),
    sqlc.arg(transport_mode),
    'pending',
    sqlc.arg(payload),
    sqlc.arg(available_at),
    sqlc.arg(expire_at)
)
returning
    command_id,
    agent_id,
    task_id,
    assignment_id,
    command_type,
    transport_mode,
    status,
    payload,
    available_at,
    expire_at,
    attempt_count,
    claim_token,
    claim_until,
    acked_at,
    finished_at,
    last_error,
    created_at,
    updated_at;

-- name: ClaimPushAgentCommands :many
with due as (
    select agent_command.command_id
    from agent_command
    where agent_command.status = 'pending'
      and agent_command.transport_mode in ('direct', 'relay')
      and agent_command.available_at <= now()
      and agent_command.expire_at > now()
    order by agent_command.available_at, agent_command.command_id
    for update skip locked
    limit sqlc.arg(limit_count)
)
update agent_command
set status = 'claimed',
    claim_token = gen_random_uuid(),
    claim_until = sqlc.arg(claim_until),
    attempt_count = agent_command.attempt_count + 1,
    last_error = null,
    updated_at = now()
from due
where agent_command.command_id = due.command_id
returning
    agent_command.command_id,
    agent_command.agent_id,
    agent_command.task_id,
    agent_command.assignment_id,
    agent_command.command_type,
    agent_command.transport_mode,
    agent_command.status,
    agent_command.payload,
    agent_command.available_at,
    agent_command.expire_at,
    agent_command.attempt_count,
    agent_command.claim_token,
    agent_command.claim_until,
    agent_command.acked_at,
    agent_command.finished_at,
    agent_command.last_error,
    agent_command.created_at,
    agent_command.updated_at;

-- name: ClaimPullAgentCommands :many
with due as (
    select agent_command.command_id
    from agent_command
    where agent_command.status = 'pending'
      and agent_command.transport_mode = 'pull'
      and agent_command.agent_id = sqlc.arg(target_agent_id)
      and agent_command.available_at <= now()
      and agent_command.expire_at > now()
    order by agent_command.available_at, agent_command.command_id
    for update skip locked
    limit sqlc.arg(limit_count)
)
update agent_command
set status = 'claimed',
    claim_token = gen_random_uuid(),
    claim_until = sqlc.arg(claim_until),
    attempt_count = agent_command.attempt_count + 1,
    last_error = null,
    updated_at = now()
from due
where agent_command.command_id = due.command_id
returning
    agent_command.command_id,
    agent_command.agent_id,
    agent_command.task_id,
    agent_command.assignment_id,
    agent_command.command_type,
    agent_command.transport_mode,
    agent_command.status,
    agent_command.payload,
    agent_command.available_at,
    agent_command.expire_at,
    agent_command.attempt_count,
    agent_command.claim_token,
    agent_command.claim_until,
    agent_command.acked_at,
    agent_command.finished_at,
    agent_command.last_error,
    agent_command.created_at,
    agent_command.updated_at;

-- name: AckAgentCommand :execrows
update agent_command
set status = 'acked',
    acked_at = sqlc.arg(acked_at),
    updated_at = now()
where command_id = sqlc.arg(command_id)
  and claim_token = sqlc.arg(claim_token)
  and status = 'claimed';

-- name: FinishAgentCommand :execrows
update agent_command
set status = 'finished',
    finished_at = sqlc.arg(finished_at),
    updated_at = now()
where command_id = sqlc.arg(command_id)
  and claim_token = sqlc.arg(claim_token)
  and status in ('claimed', 'acked');

-- name: RetryAgentCommand :execrows
update agent_command
set status = 'pending',
    available_at = sqlc.arg(next_available_at),
    claim_token = null,
    claim_until = null,
    acked_at = null,
    finished_at = null,
    last_error = sqlc.arg(last_error),
    updated_at = now()
where command_id = sqlc.arg(command_id)
  and claim_token = sqlc.arg(claim_token)
  and status in ('claimed', 'acked');

-- name: ExpireDueAgentCommands :execrows
update agent_command
set status = 'expired',
    claim_token = null,
    claim_until = null,
    updated_at = now()
where status in ('pending', 'claimed', 'acked')
  and expire_at <= sqlc.arg(cutoff);

-- name: GetAgentCommandByID :one
select
    command_id,
    agent_id,
    task_id,
    assignment_id,
    command_type,
    transport_mode,
    status,
    payload,
    available_at,
    expire_at,
    attempt_count,
    claim_token,
    claim_until,
    acked_at,
    finished_at,
    last_error,
    created_at,
    updated_at
from agent_command
where command_id = sqlc.arg(command_id);
