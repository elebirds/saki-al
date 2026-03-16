-- +goose Up
create table project (
    id uuid primary key,
    name text not null
);

-- +goose Down
drop table if exists project;
