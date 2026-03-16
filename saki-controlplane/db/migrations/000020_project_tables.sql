-- +goose Up
create table project (
    id uuid primary key,
    name text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- +goose Down
drop table if exists project;
