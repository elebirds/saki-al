-- Runtime result materialization maintenance SQL
-- Execute in maintenance window after stopping dispatcher/api writers.

-- 1) Add result materialization column (idempotent)
BEGIN;
ALTER TABLE public.task
  ADD COLUMN IF NOT EXISTS result_ready_at timestamptz NULL;
COMMIT;

-- 2) Backfill historical succeeded tasks
UPDATE public.task t
SET result_ready_at = COALESCE(t.ended_at, t.updated_at, t.created_at)
WHERE t.status = 'SUCCEEDED'::runtimetaskstatus
  AND t.result_ready_at IS NULL;

-- 3) Repair failed simulation loops caused by SELECT/score candidate race
BEGIN;

WITH target_loops AS (
  SELECT unnest(ARRAY[
    'f0d68a37-bc44-4d03-8d49-732806c0a197'::uuid,
    'dd4dab55-da1d-4540-9f67-0a3806a33753'::uuid
  ]) AS loop_id
),
latest_round AS (
  SELECT DISTINCT ON (r.loop_id) r.loop_id, r.id AS round_id
  FROM public.round r
  JOIN target_loops tl ON tl.loop_id = r.loop_id
  ORDER BY r.loop_id, r.round_index DESC, r.attempt_index DESC
),
target_select AS (
  SELECT s.id AS step_id, s.task_id, lr.round_id, lr.loop_id
  FROM latest_round lr
  JOIN public.step s ON s.round_id = lr.round_id
  WHERE s.step_type = 'SELECT'::steptype
)
UPDATE public.task t
SET status = 'READY'::runtimetaskstatus,
    assigned_executor_id = NULL,
    started_at = NULL,
    ended_at = NULL,
    last_error = NULL,
    result_ready_at = NULL,
    updated_at = now()
FROM target_select ts
WHERE t.id = ts.task_id;

WITH target_loops AS (
  SELECT unnest(ARRAY[
    'f0d68a37-bc44-4d03-8d49-732806c0a197'::uuid,
    'dd4dab55-da1d-4540-9f67-0a3806a33753'::uuid
  ]) AS loop_id
),
latest_round AS (
  SELECT DISTINCT ON (r.loop_id) r.loop_id, r.id AS round_id
  FROM public.round r
  JOIN target_loops tl ON tl.loop_id = r.loop_id
  ORDER BY r.loop_id, r.round_index DESC, r.attempt_index DESC
),
target_select AS (
  SELECT s.id AS step_id
  FROM latest_round lr
  JOIN public.step s ON s.round_id = lr.round_id
  WHERE s.step_type = 'SELECT'::steptype
)
UPDATE public.step s
SET state = 'READY'::stepstatus,
    state_version = CASE WHEN s.state <> 'READY'::stepstatus THEN s.state_version + 1 ELSE s.state_version END,
    started_at = NULL,
    ended_at = NULL,
    last_error = NULL,
    updated_at = now()
FROM target_select ts
WHERE s.id = ts.step_id;

WITH target_loops AS (
  SELECT unnest(ARRAY[
    'f0d68a37-bc44-4d03-8d49-732806c0a197'::uuid,
    'dd4dab55-da1d-4540-9f67-0a3806a33753'::uuid
  ]) AS loop_id
),
latest_round AS (
  SELECT DISTINCT ON (r.loop_id) r.loop_id, r.id AS round_id
  FROM public.round r
  JOIN target_loops tl ON tl.loop_id = r.loop_id
  ORDER BY r.loop_id, r.round_index DESC, r.attempt_index DESC
)
UPDATE public.round r
SET state = 'RUNNING'::roundstatus,
    terminal_reason = NULL,
    ended_at = NULL,
    updated_at = now()
FROM latest_round lr
WHERE r.id = lr.round_id;

WITH target_loops AS (
  SELECT unnest(ARRAY[
    'f0d68a37-bc44-4d03-8d49-732806c0a197'::uuid,
    'dd4dab55-da1d-4540-9f67-0a3806a33753'::uuid
  ]) AS loop_id
)
UPDATE public.loop l
SET lifecycle = 'RUNNING'::looplifecycle,
    phase = 'SIM_SELECT'::loopphase,
    terminal_reason = NULL,
    updated_at = now()
FROM target_loops tl
WHERE l.id = tl.loop_id
  AND l.lifecycle = 'FAILED'::looplifecycle;

COMMIT;

-- 4) Post-deploy acceptance probes
-- SELECT count(*) FROM public.task WHERE status='SUCCEEDED'::runtimetaskstatus AND result_ready_at IS NULL;
-- SELECT id, lifecycle, phase, terminal_reason FROM public.loop
--   WHERE id IN ('f0d68a37-bc44-4d03-8d49-732806c0a197','dd4dab55-da1d-4540-9f67-0a3806a33753');
