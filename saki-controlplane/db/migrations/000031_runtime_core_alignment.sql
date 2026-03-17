-- +goose Up
alter table runtime_task
    rename column claimed_by to assigned_agent_id;

alter table runtime_task
    add column task_kind text not null default 'PREDICTION',
    add column current_execution_id text,
    add column attempt integer not null default 0,
    add column max_attempts integer not null default 1,
    add column resolved_params jsonb not null default '{}'::jsonb,
    add column depends_on_task_ids uuid[] not null default '{}'::uuid[];

update runtime_task
set status = 'assigned'
where status = 'dispatching';

update runtime_task
set current_execution_id = encode(gen_random_bytes(16), 'hex')
where current_execution_id is null
  and status in ('assigned', 'running', 'cancel_requested', 'succeeded', 'failed');

alter table runtime_task
    drop column claimed_at;

alter table runtime_outbox
    add column aggregate_type text,
    add column idempotency_key text,
    add column available_at timestamptz not null default now(),
    add column attempt_count integer not null default 0,
    add column last_error text;

update runtime_outbox
set aggregate_type = 'task'
where aggregate_type is null;

update runtime_outbox
set idempotency_key = topic || ':' || aggregate_id || ':' || id::text
where idempotency_key is null;

alter table runtime_outbox
    alter column aggregate_type set not null,
    alter column aggregate_type set default 'task',
    alter column idempotency_key set not null;

create unique index if not exists runtime_outbox_idempotency_key_idx
    on runtime_outbox (idempotency_key);

create index if not exists runtime_outbox_due_idx
    on runtime_outbox (available_at, id)
    where published_at is null;

-- +goose Down
drop index if exists runtime_outbox_due_idx;
drop index if exists runtime_outbox_idempotency_key_idx;

alter table runtime_outbox
    drop column if exists last_error,
    drop column if exists attempt_count,
    drop column if exists available_at,
    drop column if exists idempotency_key,
    drop column if exists aggregate_type;

alter table runtime_task
    add column claimed_at timestamptz;

alter table runtime_task
    rename column assigned_agent_id to claimed_by;

update runtime_task
set status = 'dispatching'
where status = 'assigned';

alter table runtime_task
    drop column if exists depends_on_task_ids,
    drop column if exists resolved_params,
    drop column if exists max_attempts,
    drop column if exists attempt,
    drop column if exists current_execution_id,
    drop column if exists task_kind;
