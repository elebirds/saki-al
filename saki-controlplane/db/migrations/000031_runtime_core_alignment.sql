-- +goose Up
alter table runtime_task
    add column assigned_agent_id text;

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
do $$
begin
    raise exception '000031_runtime_core_alignment is forward-only; drain runtime and restore from backup before rollback';
end
$$;
