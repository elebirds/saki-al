-- name: CreatePendingAsset :one
insert into asset (
    kind,
    status,
    storage_backend,
    bucket,
    object_key,
    content_type,
    metadata,
    created_by
) values (
    sqlc.arg(kind),
    'pending_upload',
    sqlc.arg(storage_backend),
    sqlc.arg(bucket),
    sqlc.arg(object_key),
    sqlc.arg(content_type),
    sqlc.arg(metadata),
    sqlc.narg(created_by)::uuid
)
returning id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, created_at, updated_at;

-- name: GetAsset :one
select id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, created_at, updated_at
from asset
where id = sqlc.arg(id);

-- name: GetAssetByStorageLocation :one
select id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, created_at, updated_at
from asset
where bucket = sqlc.arg(bucket)
  and object_key = sqlc.arg(object_key);

-- name: MarkAssetReady :one
update asset
set status = 'ready',
    size_bytes = sqlc.arg(size_bytes),
    sha256_hex = sqlc.narg(sha256_hex)::text,
    content_type = sqlc.arg(content_type),
    updated_at = now()
where id = sqlc.arg(id)
  and status = 'pending_upload'
returning id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, created_at, updated_at;
