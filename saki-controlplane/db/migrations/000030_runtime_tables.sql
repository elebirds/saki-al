-- +goose Up
create type runtime_task_kind as enum ('PREDICTION');
create type runtime_task_status as enum (
    'pending',
    'assigned',
    'running',
    'cancel_requested',
    'succeeded',
    'failed',
    'canceled'
);
create type runtime_executor_status as enum ('online');

create table runtime_lease (
    name text primary key,
    holder text not null,
    epoch bigint not null,
    lease_until timestamptz not null,
    updated_at timestamptz not null default now()
);

create table runtime_task (
    id uuid primary key,
    task_kind runtime_task_kind not null default 'PREDICTION',
    task_type text not null,
    status runtime_task_status not null default 'pending',
    assigned_agent_id text,
    current_execution_id text,
    attempt integer not null default 0,
    max_attempts integer not null default 1,
    resolved_params jsonb not null default '{}'::jsonb,
    depends_on_task_ids uuid[] not null default '{}'::uuid[],
    leader_epoch bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table runtime_executor (
    id text primary key,
    version text not null,
    capabilities text[] not null default '{}',
    status runtime_executor_status not null default 'online',
    last_seen_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table runtime_outbox (
    id bigserial primary key,
    topic text not null,
    aggregate_type text not null default 'task',
    aggregate_id text not null,
    idempotency_key text not null,
    payload jsonb not null,
    available_at timestamptz not null default now(),
    attempt_count integer not null default 0,
    last_error text,
    created_at timestamptz not null default now(),
    published_at timestamptz
);

create unique index runtime_outbox_idempotency_key_idx
    on runtime_outbox (idempotency_key);

create index runtime_outbox_due_idx
    on runtime_outbox (available_at, id)
    where published_at is null;

-- +goose Down
drop table if exists runtime_outbox;
drop table if exists runtime_executor;
drop table if exists runtime_task;
drop table if exists runtime_lease;
drop type if exists runtime_executor_status;
drop type if exists runtime_task_status;
drop type if exists runtime_task_kind;
