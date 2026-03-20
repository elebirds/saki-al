-- name: GetIamPrincipalByID :one
select id, kind, display_name, status, created_at, updated_at
from iam_principal
where id = sqlc.arg(id);

-- name: CreateIamPrincipal :one
insert into iam_principal (kind, display_name)
values (sqlc.arg(kind), sqlc.arg(display_name))
returning id, kind, display_name, status, created_at, updated_at;

-- name: ListIamPrincipalsByKind :many
select id, kind, display_name, status, created_at, updated_at
from iam_principal
where kind = sqlc.arg(kind)
order by created_at desc;

-- name: UpdateIamPrincipalStatus :exec
update iam_principal
set status = sqlc.arg(status), updated_at = now()
where id = sqlc.arg(id);
