-- +goose Up
create type iam_principal_kind as enum ('human_user', 'agent', 'internal_service');
create type iam_principal_status as enum ('active', 'disabled');

create type iam_user_state as enum ('active', 'invited', 'disabled', 'deleted');

create table iam_principal (
    id uuid primary key default gen_random_uuid(),
    kind iam_principal_kind not null,
    display_name text not null,
    status iam_principal_status not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table iam_user (
    principal_id uuid primary key references iam_principal(id) on delete cascade,
    email text not null,
    username text,
    full_name text,
    avatar_asset_id uuid references asset(id) on delete set null,
    state iam_user_state not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index idx_iam_user_username on iam_user (username) where username is not null;
create unique index iam_user_email_unique on iam_user (lower(email));

create table iam_password_credential (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    -- 保留 scheme 以便未来可以并存多个认证协议或哈希方案而不破坏已有凭据。
    scheme text not null,
    password_hash text not null,
    must_change_password boolean not null default false,
    password_changed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint iam_password_credential_principal_scheme_unique unique (principal_id, scheme)
);

create index idx_iam_password_credential_principal on iam_password_credential (principal_id);

create table iam_refresh_session (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    -- family_id 用来表达“这一串 refresh token rotation 属于同一个会话家族”。
    -- 只有把 lineage 留在数据库里，controlplane 才能在发现 replay 时一次性撤销整个 family。
    family_id uuid not null,
    rotated_from uuid references iam_refresh_session(id) on delete set null,
    replaced_by uuid references iam_refresh_session(id) on delete set null,
    -- 刷新会话只保存 token 的哈希，避免数据库泄露时原始 token 被直接滥用。
    token_hash text not null unique,
    user_agent text,
    ip_address inet,
    last_seen_at timestamptz,
    revoked_at timestamptz,
    replay_detected_at timestamptz,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_iam_refresh_session_principal on iam_refresh_session (principal_id);
create index idx_iam_refresh_session_family on iam_refresh_session (family_id);
create index idx_iam_refresh_session_rotated_from on iam_refresh_session (rotated_from);
create index idx_iam_refresh_session_expires_at on iam_refresh_session (expires_at);

-- +goose Down
drop index if exists idx_iam_refresh_session_expires_at;
drop index if exists idx_iam_refresh_session_rotated_from;
drop index if exists idx_iam_refresh_session_family;
drop index if exists idx_iam_refresh_session_principal;
drop table if exists iam_refresh_session;
drop index if exists idx_iam_password_credential_principal;
drop table if exists iam_password_credential;
drop index if exists iam_user_email_unique;
drop index if exists idx_iam_user_username;
drop table if exists iam_user;
drop table if exists iam_principal;
drop type if exists iam_user_state;
drop type if exists iam_principal_status;
drop type if exists iam_principal_kind;
