-- name: ListAuthzRolePermissions :many
select role_id, permission, created_at
from authz_role_permission
where role_id = sqlc.arg(role_id)
order by permission;

-- name: AddAuthzRolePermission :exec
insert into authz_role_permission (role_id, permission)
values (sqlc.arg(role_id), sqlc.arg(permission))
on conflict (role_id, permission) do nothing;

-- name: RemoveAuthzRolePermission :exec
delete from authz_role_permission
where role_id = sqlc.arg(role_id)
  and permission = sqlc.arg(permission);
