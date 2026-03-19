-- name: CreateTaskAssignment :one
insert into task_assignment (
    task_id,
    attempt,
    agent_id,
    execution_id,
    status
)
values (
    sqlc.arg(task_id),
    sqlc.arg(attempt),
    sqlc.arg(agent_id),
    sqlc.arg(execution_id),
    sqlc.arg(status)
)
returning
    id,
    task_id,
    attempt,
    agent_id,
    execution_id,
    status,
    created_at,
    updated_at;

-- name: GetTaskAssignmentByExecutionID :one
select
    id,
    task_id,
    attempt,
    agent_id,
    execution_id,
    status,
    created_at,
    updated_at
from task_assignment
where execution_id = sqlc.arg(execution_id);
