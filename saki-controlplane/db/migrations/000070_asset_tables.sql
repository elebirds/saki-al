-- +goose Up
create table if not exists asset (
    id uuid primary key default gen_random_uuid(),
    kind text not null,
    status text not null check (status in ('pending_upload', 'ready')),
    storage_backend text not null,
    bucket text not null,
    object_key text not null,
    content_type text not null default '',
    size_bytes bigint not null default 0,
    sha256_hex text,
    metadata jsonb not null default '{}'::jsonb,
    created_by uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (bucket, object_key)
);

-- +goose Down
drop table if exists asset;
