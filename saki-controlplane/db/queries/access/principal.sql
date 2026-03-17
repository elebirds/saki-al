-- name: GetAccessPrincipalByID :one
select id, subject_type, subject_key, display_name, status, created_at, updated_at
from access_principal
where id = sqlc.arg(id);

-- name: GetAccessPrincipalBySubjectKey :one
select id, subject_type, subject_key, display_name, status, created_at, updated_at
from access_principal
where subject_type = sqlc.arg(subject_type)
  and subject_key = sqlc.arg(subject_key);

-- name: UpsertAccessPrincipal :one
insert into access_principal (
    subject_type,
    subject_key,
    display_name,
    status
)
values (
    sqlc.arg(subject_type),
    sqlc.arg(subject_key),
    sqlc.arg(display_name),
    'active'
)
on conflict (subject_type, subject_key) do update
set display_name = excluded.display_name,
    status = access_principal.status,
    updated_at = now()
returning id, subject_type, subject_key, display_name, status, created_at, updated_at;
