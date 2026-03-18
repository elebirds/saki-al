-- +goose Up
create type import_upload_session_status as enum ('initiated', 'completed', 'aborted');
create type import_task_status as enum ('queued', 'running', 'completed', 'failed');
create type import_task_event_phase as enum ('prepare', 'project_annotations_execute', 'apply_annotations');

create table import_upload_session (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    mode text not null,
    file_name text not null,
    object_key text not null,
    content_type text not null default '',
    status import_upload_session_status not null default 'initiated',
    completed_at timestamptz,
    aborted_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_import_upload_session_user_created_at on import_upload_session (user_id, created_at desc);

create table import_preview_manifest (
    token text primary key,
    mode text not null,
    project_id uuid not null,
    dataset_id uuid not null references dataset(id) on delete cascade,
    upload_session_id uuid not null references import_upload_session(id) on delete cascade,
    manifest jsonb not null,
    params_hash text not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index idx_import_preview_manifest_upload_session on import_preview_manifest (upload_session_id);

create table import_task (
    id uuid primary key,
    user_id uuid not null,
    mode text not null,
    resource_type text not null,
    resource_id uuid not null,
    status import_task_status not null default 'queued',
    payload jsonb not null default '{}'::jsonb,
    result jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_import_task_user_created_at on import_task (user_id, created_at desc);

create table import_task_event (
    seq bigserial primary key,
    task_id uuid not null references import_task(id) on delete cascade,
    event text not null,
    phase import_task_event_phase not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index idx_import_task_event_task_seq on import_task_event (task_id, seq);

create table sample_match_ref (
    id bigserial primary key,
    dataset_id uuid not null references dataset(id) on delete cascade,
    sample_id uuid not null references sample(id) on delete cascade,
    ref_type text not null,
    ref_value text not null,
    is_primary boolean not null default false,
    created_at timestamptz not null default now()
);

create index idx_sample_match_ref_exact on sample_match_ref (dataset_id, ref_type, ref_value, id);

-- +goose Down
drop table if exists sample_match_ref;
drop table if exists import_task_event;
drop table if exists import_task;
drop table if exists import_preview_manifest;
drop table if exists import_upload_session;
drop type if exists import_task_event_phase;
drop type if exists import_task_status;
drop type if exists import_upload_session_status;
