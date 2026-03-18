-- name: CreateSample :one
insert into sample (dataset_id, name, meta)
values (sqlc.arg(dataset_id), sqlc.arg(name), sqlc.arg(meta))
returning id, dataset_id, name, meta, created_at, updated_at;

-- name: GetSample :one
select id, dataset_id, name, meta, created_at, updated_at
from sample
where id = sqlc.arg(id);

-- name: ListSampleIDsByDataset :many
select id
from sample
where dataset_id = sqlc.arg(dataset_id)
order by id;
