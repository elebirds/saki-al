-- +goose Up
create type asset_kind as enum ('image', 'video', 'archive', 'document', 'binary');
create type asset_status as enum ('pending_upload', 'ready');
create type asset_storage_backend as enum ('minio');
create type asset_owner_type as enum ('project', 'dataset', 'sample');
create type asset_reference_role as enum ('attachment', 'primary');
create type asset_reference_lifecycle as enum ('durable');
create type asset_upload_intent_state as enum ('initiated', 'completed', 'canceled', 'expired');

alter table asset drop constraint if exists asset_status_check;

alter table asset
    alter column kind type asset_kind using kind::asset_kind,
    alter column status type asset_status using status::asset_status,
    alter column storage_backend type asset_storage_backend using storage_backend::asset_storage_backend;

alter table asset
    add column if not exists ready_at timestamptz,
    add column if not exists orphaned_at timestamptz;

alter table asset drop constraint if exists asset_bucket_object_key_key;
alter table asset
    add constraint asset_storage_backend_bucket_object_key_key
        unique (storage_backend, bucket, object_key);

create table if not exists asset_reference (
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

create index if not exists asset_reference_active_owner_idx
    on asset_reference (owner_type, owner_id)
    where deleted_at is null;

create index if not exists asset_reference_active_asset_idx
    on asset_reference (asset_id)
    where deleted_at is null;

create unique index if not exists asset_reference_active_asset_owner_role_key
    on asset_reference (asset_id, owner_type, owner_id, role)
    where deleted_at is null;

create unique index if not exists asset_reference_active_owner_role_primary_key
    on asset_reference (owner_type, owner_id, role)
    where is_primary and deleted_at is null;

create table if not exists asset_upload_intent (
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

create unique index if not exists asset_upload_intent_owner_role_idempotency_key
    on asset_upload_intent (owner_type, owner_id, role, idempotency_key);

create index if not exists asset_upload_intent_owner_idx
    on asset_upload_intent (owner_type, owner_id);

create index if not exists asset_upload_intent_state_expires_at_idx
    on asset_upload_intent (state, expires_at);

-- +goose Down
drop table if exists asset_upload_intent;
drop table if exists asset_reference;

alter table asset drop constraint if exists asset_storage_backend_bucket_object_key_key;
alter table asset
    add constraint asset_bucket_object_key_key unique (bucket, object_key);

alter table asset
    alter column kind type text using kind::text,
    alter column status type text using status::text,
    alter column storage_backend type text using storage_backend::text;

alter table asset
    add constraint asset_status_check check (status in ('pending_upload', 'ready'));

alter table asset
    drop column if exists ready_at,
    drop column if exists orphaned_at;

drop type if exists asset_upload_intent_state;
drop type if exists asset_reference_lifecycle;
drop type if exists asset_reference_role;
drop type if exists asset_owner_type;
drop type if exists asset_storage_backend;
drop type if exists asset_status;
drop type if exists asset_kind;
