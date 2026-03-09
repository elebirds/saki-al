-- name: ListReadyTaskIDsForDispatch :many
SELECT t.id AS id
FROM task t
LEFT JOIN step s ON s.task_id = t.id
LEFT JOIN round r ON r.id = s.round_id
LEFT JOIN loop l ON l.id = r.loop_id
WHERE (
  t.kind = 'PREDICTION'
  AND t.status IN (
    'PENDING',
    'READY',
    'RETRYING'
  )
)
OR (
  t.kind = 'STEP'
  AND t.status IN (
    'PENDING',
    'READY',
    'RETRYING'
  )
  AND l.lifecycle = 'RUNNING'::looplifecycle
)
ORDER BY t.created_at ASC
LIMIT sqlc.arg(limit_count)
FOR UPDATE OF t SKIP LOCKED;

-- name: ListDispatchLaneHeadCandidates :many
WITH candidate_tasks AS (
  SELECT
    t.id AS task_id,
    t.kind,
    t.task_type,
    t.status,
    t.plugin_id,
    t.created_at,
    t.updated_at,
    CASE
      WHEN t.kind = 'STEP' THEN r.loop_id::text
      ELSE t.id::text
    END AS lane_id,
    r.loop_id,
    COALESCE(r.resources, '{}'::jsonb) AS resources_raw,
    ROW_NUMBER() OVER (
      PARTITION BY CASE
        WHEN t.kind = 'STEP' THEN r.loop_id::text
        ELSE t.id::text
      END
      ORDER BY t.created_at ASC, t.id ASC
    ) AS lane_rank
  FROM task t
  LEFT JOIN step s ON s.task_id = t.id
  LEFT JOIN round r ON r.id = s.round_id
  LEFT JOIN loop l ON l.id = r.loop_id
  WHERE t.status IN ('PENDING', 'READY', 'RETRYING')
    AND (
      t.kind = 'PREDICTION'
      OR (
        t.kind = 'STEP'
        AND l.lifecycle = 'RUNNING'::looplifecycle
      )
    )
)
SELECT
  task_id,
  kind,
  task_type,
  status,
  plugin_id,
  created_at,
  updated_at,
  lane_id,
  loop_id,
  resources_raw
FROM candidate_tasks
WHERE lane_rank = 1
ORDER BY updated_at ASC, created_at ASC, task_id ASC
LIMIT sqlc.arg(limit_count);

-- name: GetStepPayloadByTaskIDForUpdate :one
SELECT
  t.id AS step_id,
  k.id AS task_id,
  t.round_id AS round_id,
  k.status AS task_status,
  t.step_type AS step_type,
  t.dispatch_kind AS dispatch_kind,
  t.round_index,
  k.attempt AS attempt,
  t.state_version,
  k.updated_at AS updated_at,
  COALESCE(k.depends_on_task_ids, '[]'::jsonb) AS depends_on_task_raw,
  k.resolved_params AS params_raw,
  COALESCE(k.input_commit_id, t.input_commit_id) AS input_commit_id,
  j.loop_id AS loop_id,
  j.project_id AS project_id,
  j.plugin_id,
  j.mode AS mode,
  j.resolved_params AS round_params_raw,
  j.resources AS resources_raw,
  j.input_commit_id AS round_input_commit_id,
  k.current_execution_id AS current_execution_id
FROM task k
JOIN step t ON t.task_id = k.id
JOIN round j ON j.id = t.round_id
WHERE k.id = sqlc.arg(task_id)::uuid
FOR UPDATE OF k SKIP LOCKED;

-- name: GetDependencyTaskStatusesByIDs :many
SELECT
  status,
  result_ready_at
FROM task
WHERE id = ANY(sqlc.arg(task_ids)::uuid[]);

-- name: GetLatestAssignedExecutorByTaskIDs :one
SELECT COALESCE(assigned_executor_id, '') AS assigned_executor_id
FROM task
WHERE id = ANY(sqlc.arg(task_ids)::uuid[])
ORDER BY array_position(sqlc.arg(task_ids)::uuid[], id) DESC
LIMIT 1;

-- name: GetLoopQueryBatchSize :one
SELECT query_batch_size
FROM loop
WHERE id = sqlc.arg(loop_id)::uuid;

-- name: GetSucceededScoreTaskIDByRound :one
SELECT t.id AS task_id
FROM task t
JOIN step s ON s.task_id = t.id
WHERE s.round_id = sqlc.arg(round_id)::uuid
  AND t.task_type = 'SCORE'::runtimetasktype
  AND t.status = 'SUCCEEDED'::runtimetaskstatus
  AND t.result_ready_at IS NOT NULL
ORDER BY s.step_index DESC
LIMIT 1;

-- name: GetLatestSucceededTrainTaskIDByRound :one
SELECT t.id AS task_id
FROM task t
JOIN step s ON s.task_id = t.id
WHERE s.round_id = sqlc.arg(round_id)::uuid
  AND t.task_type = 'TRAIN'::runtimetasktype
  AND t.status = 'SUCCEEDED'::runtimetaskstatus
ORDER BY s.step_index DESC
LIMIT 1;

-- name: ListTaskCandidatesByTaskID :many
SELECT
  sample_id AS sample_id,
  rank,
  score,
  reason AS reason_json,
  prediction_snapshot AS prediction_json
FROM task_candidate_item
WHERE task_id = sqlc.arg(task_id)::uuid
ORDER BY rank ASC, score DESC
LIMIT sqlc.arg(limit_count);

-- name: DeleteTaskCandidatesByTaskID :exec
DELETE FROM task_candidate_item
WHERE task_id = sqlc.arg(task_id)::uuid;

-- name: InsertTaskCandidateItem :exec
INSERT INTO task_candidate_item(
  id, task_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  sqlc.arg(candidate_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(sample_id)::uuid,
  sqlc.arg(rank),
  sqlc.arg(score),
  sqlc.arg(reason)::jsonb,
  sqlc.arg(prediction_snapshot)::jsonb,
  now(),
  now()
);

-- name: CopyTaskCandidateItems :copyfrom
INSERT INTO task_candidate_item(
  id, task_id, sample_id, rank, score, reason, prediction_snapshot, created_at, updated_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
);

-- name: UpdateStepResultProjection :execrows
UPDATE step
SET metrics = sqlc.arg(metrics)::jsonb,
    artifacts = sqlc.arg(artifacts)::jsonb,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid;

-- name: InsertTaskMetricPoint :exec
INSERT INTO task_metric_point(
  id, task_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
) VALUES (
  sqlc.arg(metric_id)::uuid,
  sqlc.arg(task_id)::uuid,
  sqlc.arg(step),
  sqlc.arg(epoch),
  sqlc.arg(metric_name),
  sqlc.arg(metric_value),
  sqlc.arg(ts),
  now(),
  now()
);

-- name: CopyTaskMetricPoints :copyfrom
INSERT INTO task_metric_point(
  id, task_id, step, epoch, metric_name, metric_value, ts, created_at, updated_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9
);

-- name: GetStepArtifactsForUpdate :one
SELECT artifacts
FROM step
WHERE id = sqlc.arg(step_id)::uuid
FOR UPDATE;

-- name: UpdateStepArtifacts :exec
UPDATE step
SET artifacts = sqlc.arg(artifacts)::jsonb,
    updated_at = now()
WHERE id = sqlc.arg(step_id)::uuid;
