-- name: CreateProject :one
insert into project (id, name)
values (gen_random_uuid(), sqlc.arg(name))
returning id, name, created_at, updated_at;
