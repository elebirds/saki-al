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
returning id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, ready_at, orphaned_at, created_at, updated_at;

-- name: GetAsset :one
select id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, ready_at, orphaned_at, created_at, updated_at
from asset
where id = sqlc.arg(id);

-- name: GetAssetByStorageLocation :one
select id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, ready_at, orphaned_at, created_at, updated_at
from asset
where bucket = sqlc.arg(bucket)
  and object_key = sqlc.arg(object_key);

-- name: MarkAssetReady :one
update asset
set status = 'ready',
    size_bytes = sqlc.arg(size_bytes),
    sha256_hex = sqlc.narg(sha256_hex)::text,
    content_type = sqlc.arg(content_type),
    ready_at = coalesce(ready_at, now()),
    orphaned_at = null,
    updated_at = now()
where id = sqlc.arg(id)
  and status = 'pending_upload'
returning id, kind, status, storage_backend, bucket, object_key, content_type, size_bytes, sha256_hex, metadata, created_by, ready_at, orphaned_at, created_at, updated_at;

-- name: ListStalePendingAssets :many
select a.id, a.kind, a.status, a.storage_backend, a.bucket, a.object_key, a.content_type, a.size_bytes, a.sha256_hex, a.metadata, a.created_by, a.ready_at, a.orphaned_at, a.created_at, a.updated_at
from asset as a
where a.status = 'pending_upload'
  and a.created_at <= sqlc.arg(cutoff)
  and not exists (
      select 1
      from asset_upload_intent as i
      where i.asset_id = a.id
        and i.state = 'initiated'
        and i.expires_at > sqlc.arg(now)
  )
  and not exists (
      select 1
      from asset_reference as r
      where r.asset_id = a.id
        and r.deleted_at is null
  )
order by a.created_at, a.id;

-- name: ListReadyOrphanedAssets :many
select a.id, a.kind, a.status, a.storage_backend, a.bucket, a.object_key, a.content_type, a.size_bytes, a.sha256_hex, a.metadata, a.created_by, a.ready_at, a.orphaned_at, a.created_at, a.updated_at
from asset as a
where a.status = 'ready'
  and a.orphaned_at is not null
  and a.orphaned_at <= sqlc.arg(cutoff)
  and not exists (
      select 1
      from asset_reference as r
      where r.asset_id = a.id
        and r.deleted_at is null
  )
order by a.orphaned_at, a.id;

-- name: GetReadyOrphanedAssetForUpdate :one
select a.id, a.kind, a.status, a.storage_backend, a.bucket, a.object_key, a.content_type, a.size_bytes, a.sha256_hex, a.metadata, a.created_by, a.ready_at, a.orphaned_at, a.created_at, a.updated_at
from asset as a
where a.id = sqlc.arg(id)
  and a.status = 'ready'
  and a.orphaned_at is not null
  and a.orphaned_at <= sqlc.arg(cutoff)
  and not exists (
      select 1
      from asset_reference as r
      where r.asset_id = a.id
        and r.deleted_at is null
  )
for update;

-- name: DeleteAsset :execrows
delete from asset
where id = sqlc.arg(id);
