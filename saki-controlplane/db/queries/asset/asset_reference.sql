-- name: CreateDurableReference :one
with locked_asset as (
    select asset.id
    from asset
    where asset.id = sqlc.arg(asset_id)
    for update
),
inserted as (
    insert into asset_reference (
        asset_id,
        owner_type,
        owner_id,
        role,
        lifecycle,
        is_primary,
        metadata,
        created_by
    )
    select
        locked_asset.id,
        sqlc.arg(owner_type),
        sqlc.arg(owner_id),
        sqlc.arg(role),
        sqlc.arg(lifecycle),
        sqlc.arg(is_primary),
        sqlc.arg(metadata),
        sqlc.narg(created_by)::uuid
    from locked_asset
    returning id, asset_id, owner_type, owner_id, role, lifecycle, is_primary, metadata, created_by, created_at, deleted_at
),
cleared as (
    update asset
    set orphaned_at = null,
        updated_at = now()
    where id in (select id from locked_asset)
)
select id, asset_id, owner_type, owner_id, role, lifecycle, is_primary, metadata, created_by, created_at, deleted_at
from inserted;

-- name: ListActiveReferencesByOwner :many
select id, asset_id, owner_type, owner_id, role, lifecycle, is_primary, metadata, created_by, created_at, deleted_at
from asset_reference
where owner_type = sqlc.arg(owner_type)
  and owner_id = sqlc.arg(owner_id)
  and deleted_at is null
order by created_at, id;

-- name: CountActiveReferencesForAsset :one
select count(*)
from asset_reference
where asset_id = sqlc.arg(asset_id)
  and deleted_at is null;

-- name: InvalidateAssetReferencesForOwner :one
with invalidated as (
    update asset_reference
    set deleted_at = sqlc.arg(deleted_at)
    where asset_reference.owner_type = sqlc.arg(owner_type)
      and asset_reference.owner_id = sqlc.arg(owner_id)
      and deleted_at is null
    returning id, asset_id
),
locked_assets as (
    select a.id
    from asset as a
    where a.id in (select distinct asset_id from invalidated)
    for update
),
orphaned as (
    update asset as a
    set orphaned_at = coalesce(a.orphaned_at, sqlc.arg(deleted_at)),
        updated_at = now()
    where a.id in (select id from locked_assets)
      and a.status = 'ready'
      and not exists (
          select 1
          from asset_reference as r
          where r.asset_id = a.id
            and r.deleted_at is null
            and not exists (
                select 1
                from invalidated as i
                where i.id = r.id
            )
      )
)
select count(*)
from invalidated;
