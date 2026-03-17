-- +goose Up
create table access_principal (
    id uuid primary key default gen_random_uuid(),
    subject_type text not null,
    subject_key text not null,
    display_name text not null,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint access_principal_status_check check (status in ('active', 'disabled')),
    constraint access_principal_subject_unique unique (subject_type, subject_key)
);

create table access_permission_grant (
    principal_id uuid not null references access_principal(id) on delete cascade,
    permission text not null,
    created_at timestamptz not null default now(),
    primary key (principal_id, permission)
);

create index idx_access_principal_status on access_principal (status, id);

-- +goose Down
drop table if exists access_permission_grant;
drop table if exists access_principal;
