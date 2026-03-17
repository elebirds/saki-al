-- name: PutSampleMatchRef :one
insert into sample_match_ref (
    dataset_id,
    sample_id,
    ref_type,
    ref_value,
    is_primary
)
values (
    sqlc.arg(dataset_id),
    sqlc.arg(sample_id),
    sqlc.arg(ref_type),
    sqlc.arg(ref_value),
    sqlc.arg(is_primary)
)
returning id, dataset_id, sample_id, ref_type, ref_value, is_primary, created_at;

-- name: FindExactSampleMatchRefs :many
select id, dataset_id, sample_id, ref_type, ref_value, is_primary, created_at
from sample_match_ref
where dataset_id = sqlc.arg(dataset_id)
  and ref_type = sqlc.arg(ref_type)
  and ref_value = sqlc.arg(ref_value)
order by id;
