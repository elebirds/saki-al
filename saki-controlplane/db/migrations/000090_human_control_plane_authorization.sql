-- +goose Up
create table authz_role (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    display_name text not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint authz_role_name_unique unique (name)
);

create table authz_role_permission (
    role_id uuid not null references authz_role(id) on delete cascade,
    permission text not null,
    created_at timestamptz not null default now(),
    primary key (role_id, permission)
);

create index idx_authz_role_permission_permission on authz_role_permission (permission);

create table authz_system_binding (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    role_id uuid not null references authz_role(id) on delete cascade,
    system_name text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint authz_system_binding_unique unique (system_name, principal_id)
);

create index idx_authz_system_binding_principal on authz_system_binding (principal_id);

create table authz_resource_membership (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    role_id uuid not null references authz_role(id) on delete cascade,
    resource_type text not null,
    resource_id uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint authz_resource_membership_unique unique (resource_type, resource_id, principal_id)
);

create index idx_authz_resource_membership_principal on authz_resource_membership (principal_id);
create index idx_authz_resource_membership_resource on authz_resource_membership (resource_type, resource_id);

-- +goose Down
drop index if exists idx_authz_resource_membership_resource;
drop index if exists idx_authz_resource_membership_principal;
drop table if exists authz_resource_membership;
drop index if exists idx_authz_system_binding_principal;
drop table if exists authz_system_binding;
drop index if exists idx_authz_role_permission_permission;
drop table if exists authz_role_permission;
drop table if exists authz_role;
