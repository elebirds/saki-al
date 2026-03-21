-- +goose Up
create type system_initialization_state as enum ('uninitialized', 'initialized');

create table system_installation (
    id uuid primary key default gen_random_uuid(),
    installation_key text not null default 'primary',
    initialization_state system_initialization_state not null default 'uninitialized',
    metadata jsonb not null default '{}'::jsonb,
    initialized_at timestamptz,
    initialized_by_principal_id uuid references iam_principal(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint system_installation_singleton_key check (installation_key = 'primary'),
    constraint system_installation_key_unique unique (installation_key)
);

create table system_setting (
    id uuid primary key default gen_random_uuid(),
    installation_id uuid not null references system_installation(id) on delete cascade,
    key text not null,
    value jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint system_setting_unique unique (installation_id, key)
);

-- +goose Down
drop table if exists system_setting;
drop table if exists system_installation;
drop type if exists system_initialization_state;
