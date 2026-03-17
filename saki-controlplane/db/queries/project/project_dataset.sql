-- name: LinkProjectDataset :one
insert into project_dataset (project_id, dataset_id)
values (sqlc.arg(project_id), sqlc.arg(dataset_id))
returning project_id, dataset_id, created_at;

-- name: UnlinkProjectDataset :exec
delete from project_dataset
where project_id = sqlc.arg(project_id)
  and dataset_id = sqlc.arg(dataset_id);

-- name: GetProjectDatasetLink :one
select project_id, dataset_id, created_at
from project_dataset
where project_id = sqlc.arg(project_id)
  and dataset_id = sqlc.arg(dataset_id);

-- name: ListProjectDatasetIDs :many
select dataset_id
from project_dataset
where project_id = sqlc.arg(project_id)
order by dataset_id;

-- name: ListProjectDatasets :many
select project_id, dataset_id, created_at
from project_dataset
where project_id = sqlc.arg(project_id)
order by dataset_id;
