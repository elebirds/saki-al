-- name: CountAuthzRoles :one
select count(*)
from authz_role
where sqlc.arg(scope_kind)::text = ''
   or scope_kind = sqlc.arg(scope_kind);

-- name: ListAuthzRoles :many
select id, scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order, created_at, updated_at
from authz_role
where sqlc.arg(scope_kind)::text = ''
   or scope_kind = sqlc.arg(scope_kind)
order by scope_kind, sort_order, name, id
limit sqlc.arg(limit_count)
offset sqlc.arg(offset_count);

-- name: GetAuthzRoleByName :one
select id, scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order, created_at, updated_at
from authz_role
where name = sqlc.arg(name);

-- name: GetAuthzRoleByID :one
select id, scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order, created_at, updated_at
from authz_role
where id = sqlc.arg(id);

-- name: CreateAuthzRole :one
insert into authz_role (scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order)
values (
    sqlc.arg(scope_kind),
    sqlc.arg(name),
    sqlc.arg(display_name),
    sqlc.arg(description),
    sqlc.arg(built_in),
    sqlc.arg(mutable),
    sqlc.arg(color),
    sqlc.arg(is_supremo),
    sqlc.arg(sort_order)
)
returning id, scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order, created_at, updated_at;

-- name: UpdateAuthzRoleMetadata :one
update authz_role
set scope_kind = sqlc.arg(scope_kind),
    display_name = sqlc.arg(display_name),
    description = sqlc.arg(description),
    built_in = sqlc.arg(built_in),
    mutable = sqlc.arg(mutable),
    color = sqlc.arg(color),
    is_supremo = sqlc.arg(is_supremo),
    sort_order = sqlc.arg(sort_order),
    updated_at = now()
where id = sqlc.arg(id)
returning id, scope_kind, name, display_name, description, built_in, mutable, color, is_supremo, sort_order, created_at, updated_at;

-- name: DeleteAuthzRole :exec
delete from authz_role
where id = sqlc.arg(id);
