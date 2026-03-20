-- name: GetIamPasswordCredentialByPrincipal :many
select id, principal_id, scheme, password_hash, must_change_password, password_changed_at, created_at, updated_at
from iam_password_credential
where principal_id = sqlc.arg(principal_id)
order by created_at desc;

-- name: CreateIamPasswordCredential :one
insert into iam_password_credential (principal_id, scheme, password_hash)
values (sqlc.arg(principal_id), sqlc.arg(scheme), sqlc.arg(password_hash))
returning id, principal_id, scheme, password_hash, must_change_password, password_changed_at, created_at, updated_at;

-- name: UpsertIamPasswordCredential :one
insert into iam_password_credential (principal_id, scheme, password_hash, must_change_password, password_changed_at)
values (
    sqlc.arg(principal_id),
    sqlc.arg(scheme),
    sqlc.arg(password_hash),
    sqlc.arg(must_change_password),
    sqlc.arg(password_changed_at)
)
on conflict (principal_id, scheme) do update
set
    password_hash = excluded.password_hash,
    must_change_password = excluded.must_change_password,
    password_changed_at = excluded.password_changed_at,
    updated_at = now()
returning id, principal_id, scheme, password_hash, must_change_password, password_changed_at, created_at, updated_at;

-- name: DeleteIamPasswordCredential :exec
delete from iam_password_credential
where principal_id = sqlc.arg(principal_id)
  and scheme = sqlc.arg(scheme);

-- name: DeleteIamPasswordCredentialsByPrincipalExcludingScheme :exec
delete from iam_password_credential
where principal_id = sqlc.arg(principal_id)
  and scheme <> sqlc.arg(scheme);
