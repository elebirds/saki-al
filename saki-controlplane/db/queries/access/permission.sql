-- name: ListAccessPermissions :many
select permission
from access_permission_grant
where principal_id = sqlc.arg(principal_id)
order by permission;

-- name: DeleteAccessPermissions :exec
delete from access_permission_grant
where principal_id = sqlc.arg(principal_id);

-- name: AddAccessPermission :exec
insert into access_permission_grant (
    principal_id,
    permission
)
values (
    sqlc.arg(principal_id),
    sqlc.arg(permission)
)
on conflict (principal_id, permission) do nothing;
