-- name: PutImportPreviewManifest :one
insert into import_preview_manifest (
    token,
    mode,
    project_id,
    dataset_id,
    upload_session_id,
    manifest,
    params_hash,
    expires_at
)
values (
    sqlc.arg(token),
    sqlc.arg(mode),
    sqlc.arg(project_id),
    sqlc.arg(dataset_id),
    sqlc.arg(upload_session_id),
    sqlc.arg(manifest),
    sqlc.arg(params_hash),
    sqlc.arg(expires_at)
)
on conflict (token) do update
set mode = excluded.mode,
    project_id = excluded.project_id,
    dataset_id = excluded.dataset_id,
    upload_session_id = excluded.upload_session_id,
    manifest = excluded.manifest,
    params_hash = excluded.params_hash,
    expires_at = excluded.expires_at
returning token, mode, project_id, dataset_id, upload_session_id, manifest, params_hash, expires_at, created_at;

-- name: GetImportPreviewManifest :one
select token, mode, project_id, dataset_id, upload_session_id, manifest, params_hash, expires_at, created_at
from import_preview_manifest
where token = sqlc.arg(token);
