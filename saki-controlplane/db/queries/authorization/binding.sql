-- name: ListAuthzSystemBindingsByPrincipal :many
select id, principal_id, role_id, system_name, created_at, updated_at
from authz_system_binding
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: ListAuthzSystemRoleNamesByPrincipal :many
select r.name
from authz_system_binding b
join authz_role r on r.id = b.role_id
where b.principal_id = sqlc.arg(principal_id)
order by r.name;

-- name: UpsertAuthzSystemBinding :one
insert into authz_system_binding (principal_id, role_id, system_name)
values (sqlc.arg(principal_id), sqlc.arg(role_id), sqlc.arg(system_name))
on conflict (system_name, principal_id) do update
set role_id = excluded.role_id,
    updated_at = now()
returning id, principal_id, role_id, system_name, created_at, updated_at;

-- name: DeleteAuthzSystemBinding :exec
delete from authz_system_binding
where id = sqlc.arg(id);
