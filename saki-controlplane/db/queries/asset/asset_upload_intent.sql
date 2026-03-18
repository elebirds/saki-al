-- name: CreateAssetUploadIntent :one
insert into asset_upload_intent (
    asset_id,
    owner_type,
    owner_id,
    role,
    is_primary,
    declared_content_type,
    idempotency_key,
    expires_at,
    created_by
) values (
    sqlc.arg(asset_id),
    sqlc.arg(owner_type),
    sqlc.arg(owner_id),
    sqlc.arg(role),
    sqlc.arg(is_primary),
    sqlc.arg(declared_content_type),
    sqlc.arg(idempotency_key),
    sqlc.arg(expires_at),
    sqlc.narg(created_by)::uuid
)
returning id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at;

-- name: GetAssetUploadIntentByAssetID :one
select id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at
from asset_upload_intent
where asset_id = sqlc.arg(asset_id);

-- name: GetAssetUploadIntentByOwnerKey :one
select id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at
from asset_upload_intent
where owner_type = sqlc.arg(owner_type)
  and owner_id = sqlc.arg(owner_id)
  and role = sqlc.arg(role)
  and idempotency_key = sqlc.arg(idempotency_key);

-- name: MarkAssetUploadIntentCompleted :one
update asset_upload_intent
set state = 'completed',
    completed_at = sqlc.arg(completed_at),
    updated_at = sqlc.arg(completed_at)
where asset_id = sqlc.arg(asset_id)
  and state = 'initiated'
returning id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at;

-- name: MarkAssetUploadIntentCanceled :one
update asset_upload_intent
set state = 'canceled',
    canceled_at = sqlc.arg(canceled_at),
    updated_at = sqlc.arg(canceled_at)
where asset_id = sqlc.arg(asset_id)
  and state = 'initiated'
returning id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at;

-- name: MarkAssetUploadIntentExpired :one
update asset_upload_intent
set state = 'expired',
    updated_at = sqlc.arg(expired_at)
where asset_id = sqlc.arg(asset_id)
  and state = 'initiated'
returning id, asset_id, owner_type, owner_id, role, is_primary, declared_content_type, state, idempotency_key, expires_at, created_by, completed_at, canceled_at, created_at, updated_at;
