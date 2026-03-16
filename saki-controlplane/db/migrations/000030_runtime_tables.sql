-- +goose Up
create table runtime_lease (
    name text primary key,
    holder text not null,
    epoch bigint not null,
    lease_until timestamptz not null,
    updated_at timestamptz not null default now()
);

create table runtime_task (
    id uuid primary key,
    task_type text not null,
    status text not null,
    claimed_by text,
    claimed_at timestamptz,
    leader_epoch bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table runtime_outbox (
    id bigserial primary key,
    topic text not null,
    aggregate_id text not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    published_at timestamptz
);

-- +goose Down
drop table if exists runtime_outbox;
drop table if exists runtime_task;
drop table if exists runtime_lease;
