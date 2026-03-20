-- name: GetIamPasswordCredentialByPrincipal :many
select id, principal_id, scheme, password_hash, created_at, updated_at
from iam_password_credential
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: CreateIamPasswordCredential :one
insert into iam_password_credential (principal_id, scheme, password_hash)
values (sqlc.arg(principal_id), sqlc.arg(scheme), sqlc.arg(password_hash))
returning id, principal_id, scheme, password_hash, created_at, updated_at;

-- name: DeleteIamPasswordCredential :exec
delete from iam_password_credential
where principal_id = sqlc.arg(principal_id)
  and scheme = sqlc.arg(scheme);
