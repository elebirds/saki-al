-- +goose Up
create type asset_kind as enum ('image', 'video', 'archive', 'document', 'binary');
create type asset_status as enum ('pending_upload', 'ready');
create type asset_storage_backend as enum ('minio');
create type asset_owner_type as enum ('project', 'dataset', 'sample');
create type asset_reference_role as enum ('attachment', 'primary');
create type asset_reference_lifecycle as enum ('durable');
create type asset_upload_intent_state as enum ('initiated', 'completed', 'canceled', 'expired');

create table asset (
    id uuid primary key default gen_random_uuid(),
    kind asset_kind not null,
    status asset_status not null default 'pending_upload',
    storage_backend asset_storage_backend not null,
    bucket text not null,
    object_key text not null,
    content_type text not null default '',
    size_bytes bigint not null default 0,
    sha256_hex text,
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid,
    ready_at timestamptz,
    orphaned_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (storage_backend, bucket, object_key)
);

create table asset_reference (
    id uuid primary key default gen_random_uuid(),
    asset_id uuid not null references asset(id) on delete cascade,
    owner_type asset_owner_type not null,
    owner_id uuid not null,
    role asset_reference_role not null,
    lifecycle asset_reference_lifecycle not null default 'durable',
    is_primary boolean not null default false,
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid,
    created_at timestamptz not null default now(),
    deleted_at timestamptz
);

create index asset_reference_active_owner_idx
    on asset_reference (owner_type, owner_id)
    where deleted_at is null;

create index asset_reference_active_asset_idx
    on asset_reference (asset_id)
    where deleted_at is null;

create unique index asset_reference_active_asset_owner_role_key
    on asset_reference (asset_id, owner_type, owner_id, role)
    where deleted_at is null;

create unique index asset_reference_active_owner_role_primary_key
    on asset_reference (owner_type, owner_id, role)
    where is_primary and deleted_at is null;

create table asset_upload_intent (
    id uuid primary key default gen_random_uuid(),
    asset_id uuid not null unique references asset(id) on delete cascade,
    owner_type asset_owner_type not null,
    owner_id uuid not null,
    role asset_reference_role not null,
    is_primary boolean not null default false,
    declared_content_type text not null,
    state asset_upload_intent_state not null default 'initiated',
    idempotency_key text not null,
    expires_at timestamptz not null,
    created_by uuid,
    completed_at timestamptz,
    canceled_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index asset_upload_intent_owner_role_idempotency_key
    on asset_upload_intent (owner_type, owner_id, role, idempotency_key);

create index asset_upload_intent_owner_idx
    on asset_upload_intent (owner_type, owner_id);

create index asset_upload_intent_state_expires_at_idx
    on asset_upload_intent (state, expires_at);

-- +goose Down
drop table if exists asset_upload_intent;
drop table if exists asset_reference;
drop table if exists asset;
drop type if exists asset_upload_intent_state;
drop type if exists asset_reference_lifecycle;
drop type if exists asset_reference_role;
drop type if exists asset_owner_type;
drop type if exists asset_storage_backend;
drop type if exists asset_status;
drop type if exists asset_kind;
