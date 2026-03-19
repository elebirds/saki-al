-- +goose Up
-- 关键设计：agent/task_assignment/agent_command 已经成为新的运行时真相，
-- 旧 runtime_executor/runtime_outbox 若继续留在 schema，会诱导后续代码继续回写废弃路径。
drop table if exists runtime_outbox;
drop table if exists runtime_executor;
drop type if exists runtime_executor_status;

-- +goose Down
create type runtime_executor_status as enum ('online');

create table runtime_executor (
    id text primary key,
    version text not null,
    capabilities text[] not null default '{}',
    status runtime_executor_status not null default 'online',
    last_seen_at timestamptz not null default now()
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
    created_at timestamptz not null default now(),
    published_at timestamptz,
    last_error text
);

create unique index runtime_outbox_idempotency_key_idx
    on runtime_outbox (idempotency_key);

create index runtime_outbox_due_idx
    on runtime_outbox (available_at, id)
    where published_at is null;
