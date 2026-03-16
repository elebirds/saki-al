-- name: CreateImportUploadSession :one
insert into import_upload_session (
    user_id,
    mode,
    file_name,
    object_key,
    content_type,
    status
)
values (
    sqlc.arg(user_id),
    sqlc.arg(mode),
    sqlc.arg(file_name),
    sqlc.arg(object_key),
    sqlc.arg(content_type),
    'initiated'
)
returning id, user_id, mode, file_name, object_key, content_type, status, completed_at, aborted_at, created_at, updated_at;

-- name: GetImportUploadSession :one
select id, user_id, mode, file_name, object_key, content_type, status, completed_at, aborted_at, created_at, updated_at
from import_upload_session
where id = sqlc.arg(id);

-- name: CompleteImportUploadSession :one
update import_upload_session
set status = 'completed',
    completed_at = now(),
    updated_at = now()
where id = sqlc.arg(id)
returning id, user_id, mode, file_name, object_key, content_type, status, completed_at, aborted_at, created_at, updated_at;

-- name: AbortImportUploadSession :one
update import_upload_session
set status = 'aborted',
    aborted_at = now(),
    updated_at = now()
where id = sqlc.arg(id)
returning id, user_id, mode, file_name, object_key, content_type, status, completed_at, aborted_at, created_at, updated_at;
