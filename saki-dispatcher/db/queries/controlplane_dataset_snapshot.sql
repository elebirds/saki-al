-- name: InsertDatasetSnapshot :exec
INSERT INTO dataset_snapshot(
  id, dataset_id, parent_snapshot_id, universe_size, max_ordinal, created_at
) VALUES (
  sqlc.arg(snapshot_id)::uuid,
  sqlc.arg(dataset_id)::uuid,
  sqlc.narg(parent_snapshot_id)::uuid,
  sqlc.arg(universe_size),
  sqlc.arg(max_ordinal),
  now()
);

-- name: InsertDatasetSnapshotSampleOrdinal :exec
INSERT INTO dataset_snapshot_sample_ordinal(
  snapshot_id, sample_uuid, ordinal, is_tombstone, tombstone_at, tombstone_reason, created_at, updated_at
) VALUES (
  sqlc.arg(snapshot_id)::uuid,
  sqlc.arg(sample_uuid)::uuid,
  sqlc.arg(ordinal),
  FALSE,
  NULL,
  NULL,
  now(),
  now()
);

-- name: MarkDatasetSnapshotSampleTombstone :exec
UPDATE dataset_snapshot_sample_ordinal
SET is_tombstone = TRUE,
    tombstone_at = now(),
    tombstone_reason = sqlc.narg(tombstone_reason)::text,
    updated_at = now()
WHERE snapshot_id = sqlc.arg(snapshot_id)::uuid
  AND sample_uuid = sqlc.arg(sample_uuid)::uuid;

-- name: UpdateDatasetSnapshotMaxOrdinal :exec
UPDATE dataset_snapshot
SET max_ordinal = sqlc.arg(max_ordinal),
    universe_size = sqlc.arg(universe_size)
WHERE id = sqlc.arg(snapshot_id)::uuid;

-- name: InsertRoundDatasetView :exec
INSERT INTO round_dataset_view(
  id, loop_id, round_id, split, is_static, snapshot_id,
  selector_encoding, selector_bytes, selector_cardinality, selector_checksum, manifest_ref,
  created_at, updated_at
) VALUES (
  sqlc.arg(view_id)::uuid,
  sqlc.arg(loop_id)::uuid,
  sqlc.arg(round_id)::uuid,
  sqlc.arg(split),
  sqlc.arg(is_static),
  sqlc.arg(snapshot_id)::uuid,
  sqlc.arg(selector_encoding),
  sqlc.arg(selector_bytes)::bytea,
  sqlc.arg(selector_cardinality),
  sqlc.arg(selector_checksum),
  sqlc.arg(manifest_ref),
  now(),
  now()
)
ON CONFLICT (round_id, split) DO UPDATE SET
  is_static = EXCLUDED.is_static,
  snapshot_id = EXCLUDED.snapshot_id,
  selector_encoding = EXCLUDED.selector_encoding,
  selector_bytes = EXCLUDED.selector_bytes,
  selector_cardinality = EXCLUDED.selector_cardinality,
  selector_checksum = EXCLUDED.selector_checksum,
  manifest_ref = EXCLUDED.manifest_ref,
  updated_at = now();

-- name: GetRoundDatasetViewBySplit :one
SELECT
  id,
  loop_id,
  round_id,
  split,
  is_static,
  snapshot_id,
  selector_encoding,
  selector_bytes,
  selector_cardinality,
  selector_checksum,
  manifest_ref,
  created_at,
  updated_at
FROM round_dataset_view
WHERE round_id = sqlc.arg(round_id)::uuid
  AND split = sqlc.arg(split)
LIMIT 1;

-- name: UpsertALSessionState :exec
INSERT INTO al_session_state(
  id, loop_id, round_id, snapshot_id, selector_encoding, selector_bytes,
  selector_cardinality, selector_checksum, selector_manifest_ref, round_index, created_at, updated_at
) VALUES (
  sqlc.arg(state_id)::uuid,
  sqlc.arg(loop_id)::uuid,
  sqlc.narg(round_id)::uuid,
  sqlc.arg(snapshot_id)::uuid,
  sqlc.arg(selector_encoding),
  sqlc.arg(selector_bytes)::bytea,
  sqlc.arg(selector_cardinality),
  sqlc.arg(selector_checksum),
  sqlc.narg(selector_manifest_ref)::text,
  sqlc.arg(round_index),
  now(),
  now()
)
ON CONFLICT (loop_id) DO UPDATE SET
  round_id = EXCLUDED.round_id,
  snapshot_id = EXCLUDED.snapshot_id,
  selector_encoding = EXCLUDED.selector_encoding,
  selector_bytes = EXCLUDED.selector_bytes,
  selector_cardinality = EXCLUDED.selector_cardinality,
  selector_checksum = EXCLUDED.selector_checksum,
  selector_manifest_ref = EXCLUDED.selector_manifest_ref,
  round_index = EXCLUDED.round_index,
  updated_at = now();

-- name: GetALSessionStateByLoopID :one
SELECT
  id,
  loop_id,
  round_id,
  snapshot_id,
  selector_encoding,
  selector_bytes,
  selector_cardinality,
  selector_checksum,
  selector_manifest_ref,
  round_index,
  created_at,
  updated_at
FROM al_session_state
WHERE loop_id = sqlc.arg(loop_id)::uuid
LIMIT 1;
