-- name: ListAuthzRoles :many
select id, name, display_name, description, created_at, updated_at
from authz_role
order by name;

-- name: GetAuthzRoleByName :one
select id, name, display_name, description, created_at, updated_at
from authz_role
where name = sqlc.arg(name);

-- name: CreateAuthzRole :one
insert into authz_role (name, display_name, description)
values (sqlc.arg(name), sqlc.arg(display_name), sqlc.arg(description))
returning id, name, display_name, description, created_at, updated_at;
