-- name: ListAuthzResourceMemberships :many
select id, principal_id, role_id, resource_type, resource_id, created_at, updated_at
from authz_resource_membership
where resource_type = sqlc.arg(resource_type)
  and resource_id = sqlc.arg(resource_id)
order by created_at desc;

-- name: ListAuthzMembershipsByPrincipal :many
select id, principal_id, role_id, resource_type, resource_id, created_at, updated_at
from authz_resource_membership
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: UpsertAuthzResourceMembership :one
insert into authz_resource_membership (principal_id, role_id, resource_type, resource_id)
values (sqlc.arg(principal_id), sqlc.arg(role_id), sqlc.arg(resource_type), sqlc.arg(resource_id))
on conflict (resource_type, resource_id, principal_id) do update
set role_id = excluded.role_id,
    updated_at = now()
returning id, principal_id, role_id, resource_type, resource_id, created_at, updated_at;

-- name: DeleteAuthzResourceMembership :exec
delete from authz_resource_membership
where id = sqlc.arg(id);
