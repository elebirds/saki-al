-- +goose Up
create table dataset (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    type text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table project_dataset (
    project_id uuid not null references project(id) on delete cascade,
    dataset_id uuid not null references dataset(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (project_id, dataset_id)
);

create table sample (
    id uuid primary key default gen_random_uuid(),
    dataset_id uuid not null references dataset(id) on delete cascade,
    name text not null default '',
    meta jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table annotation (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references project(id) on delete cascade,
    sample_id uuid not null references sample(id) on delete cascade,
    group_id text not null,
    label_id text not null,
    view text not null,
    annotation_type text not null,
    geometry jsonb not null,
    attrs jsonb not null default '{}'::jsonb,
    source text not null,
    is_generated boolean not null default false,
    created_at timestamptz not null default now()
);

create index idx_annotation_project_sample_created_at on annotation (project_id, sample_id, created_at, id);

-- +goose Down
drop table if exists annotation;
drop table if exists sample;
drop table if exists project_dataset;
drop table if exists dataset;
