-- name: CreateRuntimeTask :one
insert into runtime_task (id, task_type, status)
values (sqlc.arg(id), sqlc.arg(task_type), 'pending')
returning id, task_type, status, claimed_by, claimed_at, leader_epoch, created_at, updated_at;

-- name: ClaimPendingTask :one
with candidate as (
    select id
    from runtime_task
    where status = 'pending'
    order by created_at
    for update skip locked
    limit 1
)
update runtime_task
set status = 'dispatching',
    claimed_by = sqlc.arg(claimed_by),
    claimed_at = now(),
    leader_epoch = sqlc.arg(leader_epoch),
    updated_at = now()
where id = (select id from candidate)
returning id, task_type, status, claimed_by, claimed_at, leader_epoch, created_at, updated_at;
