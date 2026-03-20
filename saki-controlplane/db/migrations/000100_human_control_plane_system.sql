-- +goose Up
create table system_installation (
    id uuid primary key default gen_random_uuid(),
    installation_key text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index idx_system_installation_singleton on system_installation (installation_key);

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
drop index if exists idx_system_installation_singleton;
drop table if exists system_installation;
