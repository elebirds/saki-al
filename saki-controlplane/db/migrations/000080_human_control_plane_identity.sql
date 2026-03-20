-- +goose Up
create type iam_principal_status as enum ('active', 'disabled');

create type iam_user_state as enum ('active', 'invited', 'disabled');

create table iam_principal (
    id uuid primary key default gen_random_uuid(),
    kind text not null,
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
    updated_at timestamptz not null default now(),
    constraint iam_user_email_unique unique (email)
);

create unique index idx_iam_user_username on iam_user (username) where username is not null;

create table iam_password_credential (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    -- 保留 scheme 以便未来可以并存多个认证协议或哈希方案而不破坏已有凭据。
    scheme text not null,
    password_hash text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint iam_password_credential_principal_scheme_unique unique (principal_id, scheme)
);

create index idx_iam_password_credential_principal on iam_password_credential (principal_id);

create table iam_refresh_session (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references iam_principal(id) on delete cascade,
    -- 刷新会话只保存 token 的哈希，避免数据库泄露时原始 token 被直接滥用。
    token_hash text not null unique,
    user_agent text,
    ip_address inet,
    last_seen_at timestamptz,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_iam_refresh_session_principal on iam_refresh_session (principal_id);
create index idx_iam_refresh_session_expires_at on iam_refresh_session (expires_at);

-- +goose Down
drop index if exists idx_iam_refresh_session_expires_at;
drop index if exists idx_iam_refresh_session_principal;
drop table if exists iam_refresh_session;
drop index if exists idx_iam_password_credential_principal;
drop table if exists iam_password_credential;
drop index if exists idx_iam_user_username;
drop table if exists iam_user;
drop table if exists iam_principal;
drop type if exists iam_user_state;
drop type if exists iam_principal_status;
