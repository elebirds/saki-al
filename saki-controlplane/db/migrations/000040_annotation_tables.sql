-- +goose Up
create table sample (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null,
    dataset_type text not null,
    meta jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table annotation (
    id uuid primary key default gen_random_uuid(),
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

create index idx_annotation_sample_created_at on annotation (sample_id, created_at, id);

-- +goose Down
drop table if exists annotation;
drop table if exists sample;
