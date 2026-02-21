--
-- PostgreSQL database dump
--


-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: annotationsource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.annotationsource AS ENUM (
    'MANUAL',
    'MODEL',
    'SYSTEM',
    'IMPORTED'
);


--
-- Name: annotationtype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.annotationtype AS ENUM (
    'RECT',
    'OBB',
    'POLYGON',
    'POLYLINE',
    'POINT',
    'KEYPOINTS'
);


--
-- Name: auditaction; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.auditaction AS ENUM (
    'ROLE_CREATE',
    'ROLE_UPDATE',
    'ROLE_DELETE',
    'USER_ROLE_ASSIGN',
    'USER_ROLE_REVOKE',
    'MEMBER_ADD',
    'MEMBER_UPDATE',
    'MEMBER_REMOVE',
    'PERMISSION_DENIED',
    'PERMISSION_GRANTED'
);


--
-- Name: authortype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.authortype AS ENUM (
    'USER',
    'MODEL',
    'SYSTEM'
);


--
-- Name: commitsamplereviewstate; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.commitsamplereviewstate AS ENUM (
    'LABELED',
    'EMPTY_CONFIRMED'
);


--
-- Name: datasettype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.datasettype AS ENUM (
    'CLASSIC',
    'FEDO'
);


--
-- Name: loopmode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.loopmode AS ENUM (
    'ACTIVE_LEARNING',
    'SIMULATION',
    'MANUAL'
);


--
-- Name: loopphase; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.loopphase AS ENUM (
    'AL_BOOTSTRAP',
    'AL_TRAIN',
    'AL_SCORE',
    'AL_SELECT',
    'AL_WAIT_USER',
    'AL_EVAL',
    'AL_FINALIZE',
    'SIM_BOOTSTRAP',
    'SIM_TRAIN',
    'SIM_SCORE',
    'SIM_SELECT',
    'SIM_ACTIVATE',
    'SIM_EVAL',
    'SIM_FINALIZE',
    'MANUAL_BOOTSTRAP',
    'MANUAL_TRAIN',
    'MANUAL_EVAL',
    'MANUAL_EXPORT',
    'MANUAL_FINALIZE'
);


--
-- Name: loopstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.loopstatus AS ENUM (
    'DRAFT',
    'RUNNING',
    'PAUSED',
    'STOPPING',
    'STOPPED',
    'COMPLETED',
    'FAILED'
);


--
-- Name: projectstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.projectstatus AS ENUM (
    'ACTIVE',
    'ARCHIVED'
);


--
-- Name: resourcetype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.resourcetype AS ENUM (
    'DATASET',
    'PROJECT'
);


--
-- Name: roletype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.roletype AS ENUM (
    'SYSTEM',
    'RESOURCE'
);


--
-- Name: roundstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.roundstatus AS ENUM (
    'PENDING',
    'RUNNING',
    'WAIT_USER',
    'COMPLETED',
    'CANCELLED',
    'FAILED'
);


--
-- Name: stepdispatchkind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.stepdispatchkind AS ENUM (
    'DISPATCHABLE',
    'ORCHESTRATOR'
);


--
-- Name: stepstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.stepstatus AS ENUM (
    'PENDING',
    'READY',
    'DISPATCHING',
    'RUNNING',
    'RETRYING',
    'SUCCEEDED',
    'FAILED',
    'CANCELLED',
    'SKIPPED'
);


--
-- Name: steptype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.steptype AS ENUM (
    'TRAIN',
    'SCORE',
    'SELECT',
    'ACTIVATE_SAMPLES',
    'ADVANCE_BRANCH',
    'EVAL',
    'EXPORT',
    'UPLOAD_ARTIFACT',
    'CUSTOM'
);


--
-- Name: storagetype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.storagetype AS ENUM (
    'LOCAL',
    'S3'
);


--
-- Name: tasktype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tasktype AS ENUM (
    'CLASSIFICATION',
    'DETECTION',
    'SEGMENTATION'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: al_session_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.al_session_state (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    loop_id uuid NOT NULL,
    round_id uuid,
    snapshot_id uuid NOT NULL,
    selector_encoding character varying(16) NOT NULL,
    selector_bytes bytea NOT NULL,
    selector_cardinality integer NOT NULL,
    selector_checksum character varying(128) NOT NULL,
    selector_manifest_ref character varying(512),
    round_index integer NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: annotation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotation (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    sample_id uuid NOT NULL,
    label_id uuid NOT NULL,
    project_id uuid NOT NULL,
    group_id uuid NOT NULL,
    lineage_id uuid NOT NULL,
    view_role character varying NOT NULL,
    parent_id uuid,
    type public.annotationtype NOT NULL,
    source public.annotationsource NOT NULL,
    geometry jsonb,
    attrs jsonb,
    confidence double precision NOT NULL,
    annotator_id uuid
);


--
-- Name: annotation_draft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotation_draft (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    user_id uuid NOT NULL,
    branch_name character varying(100) NOT NULL,
    payload jsonb
);


--
-- Name: asset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    hash character varying(64) NOT NULL,
    storage_type public.storagetype NOT NULL,
    path character varying(1024) NOT NULL,
    bucket character varying(255),
    original_filename character varying(255) NOT NULL,
    extension character varying(31) NOT NULL,
    mime_type character varying(127) NOT NULL,
    size integer NOT NULL,
    meta_info json
);


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    created_by uuid,
    updated_by uuid,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    action public.auditaction NOT NULL,
    target_type character varying(50) NOT NULL,
    target_id uuid NOT NULL,
    old_value json,
    new_value json,
    ip_address character varying(50),
    user_agent character varying(500)
);


--
-- Name: branch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.branch (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    name character varying(100) NOT NULL,
    project_id uuid NOT NULL,
    head_commit_id uuid NOT NULL,
    description character varying(500),
    is_protected boolean NOT NULL
);


--
-- Name: commit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commit (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    project_id uuid NOT NULL,
    parent_id uuid,
    message character varying(500) NOT NULL,
    author_type public.authortype NOT NULL,
    author_id uuid,
    stats jsonb,
    extra jsonb,
    commit_hash character varying(64) NOT NULL
);


--
-- Name: commit_annotation_map; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commit_annotation_map (
    commit_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    annotation_id uuid NOT NULL,
    project_id uuid NOT NULL
);


--
-- Name: commit_sample_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.commit_sample_state (
    commit_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    project_id uuid NOT NULL,
    state public.commitsamplereviewstate NOT NULL
);


--
-- Name: dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    name character varying(200) NOT NULL,
    description character varying(2000),
    type public.datasettype NOT NULL,
    allow_duplicate_sample_names boolean NOT NULL,
    is_public boolean NOT NULL,
    owner_id uuid NOT NULL
);


--
-- Name: dataset_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset_snapshot (
    id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    parent_snapshot_id uuid,
    universe_size integer NOT NULL,
    max_ordinal integer NOT NULL,
    created_at timestamp without time zone NOT NULL
);


--
-- Name: dataset_snapshot_sample_ordinal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset_snapshot_sample_ordinal (
    snapshot_id uuid NOT NULL,
    sample_uuid uuid NOT NULL,
    ordinal integer NOT NULL,
    is_tombstone boolean NOT NULL,
    tombstone_at timestamp without time zone,
    tombstone_reason character varying(255),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: dispatch_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dispatch_outbox (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    step_id uuid NOT NULL,
    executor_id character varying(128) NOT NULL,
    request_id character varying(128) NOT NULL,
    payload jsonb,
    status character varying(32) NOT NULL,
    attempt_count integer NOT NULL,
    next_attempt_at timestamp without time zone NOT NULL,
    locked_at timestamp without time zone,
    sent_at timestamp without time zone,
    last_error character varying(4000)
);


--
-- Name: import_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_task (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    mode character varying(64) NOT NULL,
    resource_type character varying(32) NOT NULL,
    resource_id uuid NOT NULL,
    user_id uuid NOT NULL,
    status character varying(32) NOT NULL,
    progress_current integer NOT NULL,
    progress_total integer NOT NULL,
    phase character varying(128),
    payload jsonb,
    summary jsonb,
    error character varying(2000),
    started_at timestamp without time zone,
    finished_at timestamp without time zone
);


--
-- Name: import_task_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_task_event (
    id uuid NOT NULL,
    task_id uuid NOT NULL,
    seq integer NOT NULL,
    ts timestamp without time zone NOT NULL,
    event_type character varying(32) NOT NULL,
    event_subtype character varying(64),
    phase character varying(128),
    message character varying(2000),
    current integer,
    total integer,
    item_key character varying(1024),
    status character varying(128),
    detail jsonb
);


--
-- Name: label; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.label (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    name character varying NOT NULL,
    color character varying NOT NULL,
    description character varying,
    sort_order integer NOT NULL,
    shortcut character varying(10),
    project_id uuid NOT NULL
);


--
-- Name: loop; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.loop (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    branch_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    mode public.loopmode NOT NULL,
    phase public.loopphase NOT NULL,
    phase_meta jsonb,
    model_arch character varying NOT NULL,
    experiment_group_id uuid,
    config jsonb,
    current_iteration integer NOT NULL,
    status public.loopstatus NOT NULL,
    max_rounds integer NOT NULL,
    query_batch_size integer NOT NULL,
    min_seed_labeled integer NOT NULL,
    min_new_labels_per_round integer NOT NULL,
    stop_patience_rounds integer NOT NULL,
    stop_min_gain double precision NOT NULL,
    auto_register_model boolean NOT NULL,
    last_confirmed_commit_id uuid,
    terminal_reason character varying(4000)
);


--
-- Name: model; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_commit_id uuid,
    parent_model_id uuid,
    plugin_id character varying NOT NULL,
    model_arch character varying NOT NULL,
    name character varying NOT NULL,
    version_tag character varying NOT NULL,
    weights_path character varying NOT NULL,
    status character varying NOT NULL,
    metrics jsonb,
    artifacts jsonb,
    promoted_at timestamp without time zone,
    created_by uuid
);


--
-- Name: project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    name character varying NOT NULL,
    description character varying,
    task_type public.tasktype NOT NULL,
    dataset_type public.datasettype NOT NULL,
    enabled_annotation_types jsonb,
    status public.projectstatus NOT NULL,
    config jsonb
);


--
-- Name: project_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_dataset (
    project_id uuid NOT NULL,
    dataset_id uuid NOT NULL
);


--
-- Name: resource_member; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resource_member (
    created_by uuid,
    updated_by uuid,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    resource_type public.resourcetype NOT NULL,
    resource_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_id uuid NOT NULL
);


--
-- Name: role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    is_system boolean NOT NULL,
    is_default boolean NOT NULL,
    is_super_admin boolean NOT NULL,
    is_admin boolean NOT NULL,
    display_name character varying(100) NOT NULL,
    description character varying(500),
    sort_order integer NOT NULL,
    name character varying(50) NOT NULL,
    type public.roletype NOT NULL,
    color character varying(50) NOT NULL,
    is_supremo boolean NOT NULL
);


--
-- Name: role_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permission (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    permission character varying(100) NOT NULL,
    role_id uuid NOT NULL
);


--
-- Name: round; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.round (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    project_id uuid NOT NULL,
    loop_id uuid NOT NULL,
    round_index integer NOT NULL,
    mode public.loopmode NOT NULL,
    state public.roundstatus NOT NULL,
    step_counts jsonb,
    round_type character varying NOT NULL,
    plugin_id character varying NOT NULL,
    resolved_params jsonb,
    resources jsonb,
    input_commit_id uuid,
    output_commit_id uuid,
    assigned_executor_id character varying,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    retry_count integer NOT NULL,
    terminal_reason character varying(4000),
    final_metrics jsonb,
    final_artifacts jsonb,
    strategy_params jsonb
);


--
-- Name: round_dataset_view; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.round_dataset_view (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    loop_id uuid NOT NULL,
    round_id uuid NOT NULL,
    split character varying(32) NOT NULL,
    is_static boolean NOT NULL,
    snapshot_id uuid NOT NULL,
    selector_encoding character varying(16) NOT NULL,
    selector_bytes bytea NOT NULL,
    selector_cardinality integer NOT NULL,
    selector_checksum character varying(128) NOT NULL,
    manifest_ref character varying(512) NOT NULL
);


--
-- Name: round_sample_metric; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.round_sample_metric (
    id uuid NOT NULL,
    round_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    score double precision NOT NULL,
    extra jsonb,
    prediction_snapshot jsonb
);


--
-- Name: runtime_command_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_command_log (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    command_id character varying(128) NOT NULL,
    command_type character varying(64) NOT NULL,
    resource_id character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    detail character varying NOT NULL
);


--
-- Name: runtime_executor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_executor (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    executor_id character varying(128) NOT NULL,
    node_id character varying(128),
    version character varying(64) NOT NULL,
    runtime_kind character varying(32),
    status character varying(32) NOT NULL,
    is_online boolean NOT NULL,
    current_step_id character varying(64),
    plugin_ids jsonb,
    resources jsonb,
    hardware_profile jsonb,
    mps_stability_profile jsonb,
    kernel_compat_flags jsonb,
    health_status character varying(32),
    health_detail jsonb,
    uptime_sec integer,
    last_seen_at timestamp without time zone,
    last_error character varying(4000)
);


--
-- Name: runtime_executor_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_executor_stats (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    ts timestamp without time zone NOT NULL,
    total_count integer NOT NULL,
    online_count integer NOT NULL,
    busy_count integer NOT NULL,
    available_count integer NOT NULL,
    availability_rate double precision NOT NULL,
    pending_assign_count integer NOT NULL,
    pending_stop_count integer NOT NULL
);


--
-- Name: sample; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    dataset_id uuid NOT NULL,
    name character varying NOT NULL,
    asset_group json,
    primary_asset_id uuid,
    remark character varying NOT NULL,
    meta_info json
);


--
-- Name: step; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.step (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    round_id uuid NOT NULL,
    step_type public.steptype NOT NULL,
    dispatch_kind public.stepdispatchkind NOT NULL,
    state public.stepstatus NOT NULL,
    round_index integer NOT NULL,
    step_index integer NOT NULL,
    depends_on_step_ids jsonb,
    resolved_params jsonb,
    metrics jsonb,
    artifacts jsonb,
    dataset_manifest_ref character varying(512),
    snapshot_id uuid,
    env_overrides jsonb,
    runtime_hints jsonb,
    kernel_capability_requirements jsonb,
    gpu_exclusive boolean NOT NULL,
    kernel_id character varying(128),
    kernel_version character varying(128),
    input_commit_id uuid,
    output_commit_id uuid,
    assigned_executor_id character varying,
    dispatch_request_id character varying(128),
    state_version integer NOT NULL,
    attempt integer NOT NULL,
    max_attempts integer NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    last_error character varying(4000)
);


--
-- Name: step_candidate_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.step_candidate_item (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    step_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    rank integer NOT NULL,
    score double precision NOT NULL,
    reason jsonb,
    prediction_snapshot jsonb
);


--
-- Name: step_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.step_event (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    step_id uuid NOT NULL,
    seq integer NOT NULL,
    ts timestamp without time zone NOT NULL,
    event_type character varying(64) NOT NULL,
    payload jsonb,
    request_id character varying(128)
);


--
-- Name: step_metric_point; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.step_metric_point (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    step_id uuid NOT NULL,
    step integer NOT NULL,
    epoch integer,
    metric_name character varying(128) NOT NULL,
    metric_value double precision NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: system_setting; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_setting (
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    key character varying(128) NOT NULL,
    value_json json,
    updated_by uuid
);


--
-- Name: user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."user" (
    id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    email character varying(255) NOT NULL,
    full_name character varying(100),
    is_active boolean NOT NULL,
    avatar_url character varying(500),
    must_change_password boolean NOT NULL,
    hashed_password character varying NOT NULL
);


--
-- Name: user_system_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_system_role (
    created_by uuid,
    updated_by uuid,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_id uuid NOT NULL,
    expires_at timestamp without time zone
);


--
-- Name: al_session_state al_session_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.al_session_state
    ADD CONSTRAINT al_session_state_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: annotation_draft annotation_draft_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_draft
    ADD CONSTRAINT annotation_draft_pkey PRIMARY KEY (id);


--
-- Name: annotation annotation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_pkey PRIMARY KEY (id);


--
-- Name: asset asset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset
    ADD CONSTRAINT asset_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: branch branch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branch
    ADD CONSTRAINT branch_pkey PRIMARY KEY (id);


--
-- Name: commit_annotation_map commit_annotation_map_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_annotation_map
    ADD CONSTRAINT commit_annotation_map_pkey PRIMARY KEY (commit_id, sample_id, annotation_id);


--
-- Name: commit commit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit
    ADD CONSTRAINT commit_pkey PRIMARY KEY (id);


--
-- Name: commit_sample_state commit_sample_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_sample_state
    ADD CONSTRAINT commit_sample_state_pkey PRIMARY KEY (commit_id, sample_id);


--
-- Name: dataset dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset
    ADD CONSTRAINT dataset_pkey PRIMARY KEY (id);


--
-- Name: dataset_snapshot dataset_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_snapshot
    ADD CONSTRAINT dataset_snapshot_pkey PRIMARY KEY (id);


--
-- Name: dataset_snapshot_sample_ordinal dataset_snapshot_sample_ordinal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_snapshot_sample_ordinal
    ADD CONSTRAINT dataset_snapshot_sample_ordinal_pkey PRIMARY KEY (snapshot_id, sample_uuid);


--
-- Name: dispatch_outbox dispatch_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispatch_outbox
    ADD CONSTRAINT dispatch_outbox_pkey PRIMARY KEY (id);


--
-- Name: import_task_event import_task_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event
    ADD CONSTRAINT import_task_event_pkey PRIMARY KEY (id);


--
-- Name: import_task import_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task
    ADD CONSTRAINT import_task_pkey PRIMARY KEY (id);


--
-- Name: label label_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.label
    ADD CONSTRAINT label_pkey PRIMARY KEY (id);


--
-- Name: loop loop_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loop
    ADD CONSTRAINT loop_pkey PRIMARY KEY (id);


--
-- Name: model model_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model
    ADD CONSTRAINT model_pkey PRIMARY KEY (id);


--
-- Name: project_dataset project_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dataset
    ADD CONSTRAINT project_dataset_pkey PRIMARY KEY (project_id, dataset_id);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (id);


--
-- Name: resource_member resource_member_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT resource_member_pkey PRIMARY KEY (id);


--
-- Name: role_permission role_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_pkey PRIMARY KEY (id);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (id);


--
-- Name: round_dataset_view round_dataset_view_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_dataset_view
    ADD CONSTRAINT round_dataset_view_pkey PRIMARY KEY (id);


--
-- Name: round round_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT round_pkey PRIMARY KEY (id);


--
-- Name: round_sample_metric round_sample_metric_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_sample_metric
    ADD CONSTRAINT round_sample_metric_pkey PRIMARY KEY (id, round_id, sample_id);


--
-- Name: runtime_command_log runtime_command_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_command_log
    ADD CONSTRAINT runtime_command_log_pkey PRIMARY KEY (id);


--
-- Name: runtime_executor runtime_executor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_executor
    ADD CONSTRAINT runtime_executor_pkey PRIMARY KEY (id);


--
-- Name: runtime_executor_stats runtime_executor_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_executor_stats
    ADD CONSTRAINT runtime_executor_stats_pkey PRIMARY KEY (id);


--
-- Name: sample sample_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample
    ADD CONSTRAINT sample_pkey PRIMARY KEY (id);


--
-- Name: step_candidate_item step_candidate_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_candidate_item
    ADD CONSTRAINT step_candidate_item_pkey PRIMARY KEY (id);


--
-- Name: step_event step_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_event
    ADD CONSTRAINT step_event_pkey PRIMARY KEY (id);


--
-- Name: step_metric_point step_metric_point_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_metric_point
    ADD CONSTRAINT step_metric_point_pkey PRIMARY KEY (id);


--
-- Name: step step_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT step_pkey PRIMARY KEY (id);


--
-- Name: system_setting system_setting_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting
    ADD CONSTRAINT system_setting_pkey PRIMARY KEY (key);


--
-- Name: annotation_draft uq_annotation_draft; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_draft
    ADD CONSTRAINT uq_annotation_draft UNIQUE (project_id, sample_id, user_id, branch_name);


--
-- Name: import_task_event uq_import_task_event_task_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event
    ADD CONSTRAINT uq_import_task_event_task_seq UNIQUE (task_id, seq);


--
-- Name: loop uq_loop_branch_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loop
    ADD CONSTRAINT uq_loop_branch_id UNIQUE (branch_id);


--
-- Name: branch uq_project_branch_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branch
    ADD CONSTRAINT uq_project_branch_name UNIQUE (project_id, name);


--
-- Name: label uq_project_label_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.label
    ADD CONSTRAINT uq_project_label_name UNIQUE (project_id, name);


--
-- Name: resource_member uq_resource_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT uq_resource_member UNIQUE (resource_type, resource_id, user_id);


--
-- Name: round uq_round_loop_round; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT uq_round_loop_round UNIQUE (loop_id, round_index);


--
-- Name: step_candidate_item uq_step_candidate_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_candidate_item
    ADD CONSTRAINT uq_step_candidate_item UNIQUE (step_id, sample_id);


--
-- Name: step_event uq_step_event_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_event
    ADD CONSTRAINT uq_step_event_seq UNIQUE (step_id, seq);


--
-- Name: step uq_step_order; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT uq_step_order UNIQUE (round_id, step_index);


--
-- Name: user user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (id);


--
-- Name: user_system_role user_system_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_system_role
    ADD CONSTRAINT user_system_role_pkey PRIMARY KEY (id);


--
-- Name: idx_commit_sample_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commit_sample_lookup ON public.commit_annotation_map USING btree (commit_id, sample_id, annotation_id);


--
-- Name: idx_commit_sample_state_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_commit_sample_state_lookup ON public.commit_sample_state USING btree (commit_id, sample_id, state);


--
-- Name: ix_al_session_state_loop_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_al_session_state_loop_id ON public.al_session_state USING btree (loop_id);


--
-- Name: ix_annotation_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_confidence ON public.annotation USING btree (confidence);


--
-- Name: ix_annotation_draft_branch_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_draft_branch_name ON public.annotation_draft USING btree (branch_name);


--
-- Name: ix_annotation_draft_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_draft_project_id ON public.annotation_draft USING btree (project_id);


--
-- Name: ix_annotation_draft_sample_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_draft_sample_id ON public.annotation_draft USING btree (sample_id);


--
-- Name: ix_annotation_draft_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_draft_user_id ON public.annotation_draft USING btree (user_id);


--
-- Name: ix_annotation_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_group_id ON public.annotation USING btree (group_id);


--
-- Name: ix_annotation_label_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_label_id ON public.annotation USING btree (label_id);


--
-- Name: ix_annotation_lineage_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_lineage_id ON public.annotation USING btree (lineage_id);


--
-- Name: ix_annotation_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_parent_id ON public.annotation USING btree (parent_id);


--
-- Name: ix_annotation_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_project_id ON public.annotation USING btree (project_id);


--
-- Name: ix_annotation_sample_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_sample_id ON public.annotation USING btree (sample_id);


--
-- Name: ix_annotation_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_source ON public.annotation USING btree (source);


--
-- Name: ix_annotation_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_type ON public.annotation USING btree (type);


--
-- Name: ix_asset_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_asset_hash ON public.asset USING btree (hash);


--
-- Name: ix_audit_log_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_log_action ON public.audit_log USING btree (action);


--
-- Name: ix_audit_log_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_log_created_by ON public.audit_log USING btree (created_by);


--
-- Name: ix_audit_log_updated_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_log_updated_by ON public.audit_log USING btree (updated_by);


--
-- Name: ix_branch_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_branch_name ON public.branch USING btree (name);


--
-- Name: ix_branch_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_branch_project_id ON public.branch USING btree (project_id);


--
-- Name: ix_commit_annotation_map_annotation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_annotation_map_annotation_id ON public.commit_annotation_map USING btree (annotation_id);


--
-- Name: ix_commit_annotation_map_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_annotation_map_commit_id ON public.commit_annotation_map USING btree (commit_id);


--
-- Name: ix_commit_annotation_map_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_annotation_map_project_id ON public.commit_annotation_map USING btree (project_id);


--
-- Name: ix_commit_annotation_map_sample_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_annotation_map_sample_id ON public.commit_annotation_map USING btree (sample_id);


--
-- Name: ix_commit_author_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_author_type ON public.commit USING btree (author_type);


--
-- Name: ix_commit_commit_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_commit_hash ON public.commit USING btree (commit_hash);


--
-- Name: ix_commit_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_parent_id ON public.commit USING btree (parent_id);


--
-- Name: ix_commit_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_project_id ON public.commit USING btree (project_id);


--
-- Name: ix_commit_sample_state_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_sample_state_commit_id ON public.commit_sample_state USING btree (commit_id);


--
-- Name: ix_commit_sample_state_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_sample_state_project_id ON public.commit_sample_state USING btree (project_id);


--
-- Name: ix_commit_sample_state_sample_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_sample_state_sample_id ON public.commit_sample_state USING btree (sample_id);


--
-- Name: ix_commit_sample_state_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_commit_sample_state_state ON public.commit_sample_state USING btree (state);


--
-- Name: ix_dataset_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dataset_owner_id ON public.dataset USING btree (owner_id);


--
-- Name: ix_dataset_snapshot_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dataset_snapshot_dataset_id ON public.dataset_snapshot USING btree (dataset_id);


--
-- Name: ix_dataset_snapshot_parent_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dataset_snapshot_parent_snapshot_id ON public.dataset_snapshot USING btree (parent_snapshot_id);


--
-- Name: ix_dispatch_outbox_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_dispatch_outbox_request_id ON public.dispatch_outbox USING btree (request_id);


--
-- Name: ix_dispatch_outbox_status_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dispatch_outbox_status_next_attempt_at ON public.dispatch_outbox USING btree (status, next_attempt_at);


--
-- Name: ix_dispatch_outbox_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dispatch_outbox_step_id ON public.dispatch_outbox USING btree (step_id);


--
-- Name: ix_import_task_event_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_event_event_type ON public.import_task_event USING btree (event_type);


--
-- Name: ix_import_task_event_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_event_seq ON public.import_task_event USING btree (seq);


--
-- Name: ix_import_task_event_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_event_task_id ON public.import_task_event USING btree (task_id);


--
-- Name: ix_import_task_event_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_event_ts ON public.import_task_event USING btree (ts);


--
-- Name: ix_import_task_finished_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_finished_at ON public.import_task USING btree (finished_at);


--
-- Name: ix_import_task_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_mode ON public.import_task USING btree (mode);


--
-- Name: ix_import_task_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_resource_id ON public.import_task USING btree (resource_id);


--
-- Name: ix_import_task_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_resource_type ON public.import_task USING btree (resource_type);


--
-- Name: ix_import_task_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_started_at ON public.import_task USING btree (started_at);


--
-- Name: ix_import_task_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_status ON public.import_task USING btree (status);


--
-- Name: ix_import_task_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_task_user_id ON public.import_task USING btree (user_id);


--
-- Name: ix_label_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_label_project_id ON public.label USING btree (project_id);


--
-- Name: ix_loop_branch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_branch_id ON public.loop USING btree (branch_id);


--
-- Name: ix_loop_experiment_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_experiment_group_id ON public.loop USING btree (experiment_group_id);


--
-- Name: ix_loop_last_confirmed_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_last_confirmed_commit_id ON public.loop USING btree (last_confirmed_commit_id);


--
-- Name: ix_loop_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_mode ON public.loop USING btree (mode);


--
-- Name: ix_loop_phase; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_phase ON public.loop USING btree (phase);


--
-- Name: ix_loop_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_project_id ON public.loop USING btree (project_id);


--
-- Name: ix_loop_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_loop_status ON public.loop USING btree (status);


--
-- Name: ix_model_model_arch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_model_arch ON public.model USING btree (model_arch);


--
-- Name: ix_model_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_name ON public.model USING btree (name);


--
-- Name: ix_model_parent_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_parent_model_id ON public.model USING btree (parent_model_id);


--
-- Name: ix_model_plugin_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_plugin_id ON public.model USING btree (plugin_id);


--
-- Name: ix_model_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_project_id ON public.model USING btree (project_id);


--
-- Name: ix_model_source_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_source_commit_id ON public.model USING btree (source_commit_id);


--
-- Name: ix_project_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_name ON public.project USING btree (name);


--
-- Name: ix_resource_member_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resource_member_created_by ON public.resource_member USING btree (created_by);


--
-- Name: ix_resource_member_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resource_member_resource_id ON public.resource_member USING btree (resource_id);


--
-- Name: ix_resource_member_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resource_member_resource_type ON public.resource_member USING btree (resource_type);


--
-- Name: ix_resource_member_updated_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resource_member_updated_by ON public.resource_member USING btree (updated_by);


--
-- Name: ix_resource_member_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resource_member_user_id ON public.resource_member USING btree (user_id);


--
-- Name: ix_role_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_role_name ON public.role USING btree (name);


--
-- Name: ix_role_permission_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permission_role_id ON public.role_permission USING btree (role_id);


--
-- Name: ix_round_assigned_executor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_assigned_executor_id ON public.round USING btree (assigned_executor_id);


--
-- Name: ix_round_dataset_view_loop_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_dataset_view_loop_id ON public.round_dataset_view USING btree (loop_id);


--
-- Name: ix_round_dataset_view_round_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_dataset_view_round_id ON public.round_dataset_view USING btree (round_id);


--
-- Name: ix_round_dataset_view_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_dataset_view_snapshot_id ON public.round_dataset_view USING btree (snapshot_id);


--
-- Name: ix_round_loop_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_loop_id ON public.round USING btree (loop_id);


--
-- Name: ix_round_plugin_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_plugin_id ON public.round USING btree (plugin_id);


--
-- Name: ix_round_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_project_id ON public.round USING btree (project_id);


--
-- Name: ix_round_round_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_round_index ON public.round USING btree (round_index);


--
-- Name: ix_round_round_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_round_type ON public.round USING btree (round_type);


--
-- Name: ix_round_sample_metric_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_sample_metric_score ON public.round_sample_metric USING btree (score);


--
-- Name: ix_round_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_round_state ON public.round USING btree (state);


--
-- Name: ix_runtime_command_log_command_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_runtime_command_log_command_id ON public.runtime_command_log USING btree (command_id);


--
-- Name: ix_runtime_command_log_command_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_command_log_command_type ON public.runtime_command_log USING btree (command_type);


--
-- Name: ix_runtime_command_log_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_command_log_resource_id ON public.runtime_command_log USING btree (resource_id);


--
-- Name: ix_runtime_command_log_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_command_log_status ON public.runtime_command_log USING btree (status);


--
-- Name: ix_runtime_executor_current_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_current_step_id ON public.runtime_executor USING btree (current_step_id);


--
-- Name: ix_runtime_executor_executor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_runtime_executor_executor_id ON public.runtime_executor USING btree (executor_id);


--
-- Name: ix_runtime_executor_is_online; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_is_online ON public.runtime_executor USING btree (is_online);


--
-- Name: ix_runtime_executor_last_seen_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_last_seen_at ON public.runtime_executor USING btree (last_seen_at);


--
-- Name: ix_runtime_executor_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_node_id ON public.runtime_executor USING btree (node_id);


--
-- Name: ix_runtime_executor_stats_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_stats_ts ON public.runtime_executor_stats USING btree (ts);


--
-- Name: ix_runtime_executor_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_executor_status ON public.runtime_executor USING btree (status);


--
-- Name: ix_sample_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sample_dataset_id ON public.sample USING btree (dataset_id);


--
-- Name: ix_sample_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sample_name ON public.sample USING btree (name);


--
-- Name: ix_step_assigned_executor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_assigned_executor_id ON public.step USING btree (assigned_executor_id);


--
-- Name: ix_step_candidate_item_sample_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_candidate_item_sample_id ON public.step_candidate_item USING btree (sample_id);


--
-- Name: ix_step_candidate_item_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_candidate_item_step_id ON public.step_candidate_item USING btree (step_id);


--
-- Name: ix_step_dispatch_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_dispatch_kind ON public.step USING btree (dispatch_kind);


--
-- Name: ix_step_dispatch_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_dispatch_request_id ON public.step USING btree (dispatch_request_id);


--
-- Name: ix_step_event_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_event_event_type ON public.step_event USING btree (event_type);


--
-- Name: ix_step_event_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_event_seq ON public.step_event USING btree (seq);


--
-- Name: ix_step_event_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_event_step_id ON public.step_event USING btree (step_id);


--
-- Name: ix_step_event_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_event_ts ON public.step_event USING btree (ts);


--
-- Name: ix_step_input_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_input_commit_id ON public.step USING btree (input_commit_id);


--
-- Name: ix_step_metric_point_epoch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_metric_point_epoch ON public.step_metric_point USING btree (epoch);


--
-- Name: ix_step_metric_point_metric_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_metric_point_metric_name ON public.step_metric_point USING btree (metric_name);


--
-- Name: ix_step_metric_point_step; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_metric_point_step ON public.step_metric_point USING btree (step);


--
-- Name: ix_step_metric_point_step_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_metric_point_step_id ON public.step_metric_point USING btree (step_id);


--
-- Name: ix_step_metric_point_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_metric_point_ts ON public.step_metric_point USING btree (ts);


--
-- Name: ix_step_output_commit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_output_commit_id ON public.step USING btree (output_commit_id);


--
-- Name: ix_step_round_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_round_id ON public.step USING btree (round_id);


--
-- Name: ix_step_round_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_round_index ON public.step USING btree (round_index);


--
-- Name: ix_step_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_snapshot_id ON public.step USING btree (snapshot_id);


--
-- Name: ix_step_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_state ON public.step USING btree (state);


--
-- Name: ix_step_step_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_step_index ON public.step USING btree (step_index);


--
-- Name: ix_step_step_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_step_step_type ON public.step USING btree (step_type);


--
-- Name: ix_system_setting_updated_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_updated_by ON public.system_setting USING btree (updated_by);


--
-- Name: ix_user_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_email ON public."user" USING btree (email);


--
-- Name: ix_user_system_role_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_system_role_created_by ON public.user_system_role USING btree (created_by);


--
-- Name: ix_user_system_role_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_system_role_role_id ON public.user_system_role USING btree (role_id);


--
-- Name: ix_user_system_role_updated_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_system_role_updated_by ON public.user_system_role USING btree (updated_by);


--
-- Name: ix_user_system_role_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_system_role_user_id ON public.user_system_role USING btree (user_id);


--
-- Name: al_session_state al_session_state_loop_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.al_session_state
    ADD CONSTRAINT al_session_state_loop_id_fkey FOREIGN KEY (loop_id) REFERENCES public.loop(id);


--
-- Name: al_session_state al_session_state_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.al_session_state
    ADD CONSTRAINT al_session_state_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.round(id);


--
-- Name: al_session_state al_session_state_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.al_session_state
    ADD CONSTRAINT al_session_state_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.dataset_snapshot(id);


--
-- Name: annotation_draft annotation_draft_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_draft
    ADD CONSTRAINT annotation_draft_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: annotation_draft annotation_draft_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_draft
    ADD CONSTRAINT annotation_draft_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: annotation_draft annotation_draft_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_draft
    ADD CONSTRAINT annotation_draft_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: annotation annotation_label_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_label_id_fkey FOREIGN KEY (label_id) REFERENCES public.label(id);


--
-- Name: annotation annotation_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.annotation(id);


--
-- Name: annotation annotation_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: annotation annotation_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: audit_log audit_log_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_created_by_fkey FOREIGN KEY (created_by) REFERENCES public."user"(id);


--
-- Name: audit_log audit_log_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public."user"(id);


--
-- Name: branch branch_head_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branch
    ADD CONSTRAINT branch_head_commit_id_fkey FOREIGN KEY (head_commit_id) REFERENCES public.commit(id);


--
-- Name: branch branch_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.branch
    ADD CONSTRAINT branch_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: commit_annotation_map commit_annotation_map_annotation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_annotation_map
    ADD CONSTRAINT commit_annotation_map_annotation_id_fkey FOREIGN KEY (annotation_id) REFERENCES public.annotation(id);


--
-- Name: commit_annotation_map commit_annotation_map_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_annotation_map
    ADD CONSTRAINT commit_annotation_map_commit_id_fkey FOREIGN KEY (commit_id) REFERENCES public.commit(id);


--
-- Name: commit_annotation_map commit_annotation_map_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_annotation_map
    ADD CONSTRAINT commit_annotation_map_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: commit_annotation_map commit_annotation_map_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_annotation_map
    ADD CONSTRAINT commit_annotation_map_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: commit commit_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit
    ADD CONSTRAINT commit_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.commit(id);


--
-- Name: commit commit_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit
    ADD CONSTRAINT commit_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: commit_sample_state commit_sample_state_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_sample_state
    ADD CONSTRAINT commit_sample_state_commit_id_fkey FOREIGN KEY (commit_id) REFERENCES public.commit(id);


--
-- Name: commit_sample_state commit_sample_state_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_sample_state
    ADD CONSTRAINT commit_sample_state_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: commit_sample_state commit_sample_state_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.commit_sample_state
    ADD CONSTRAINT commit_sample_state_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: dataset dataset_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset
    ADD CONSTRAINT dataset_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public."user"(id);


--
-- Name: dataset_snapshot dataset_snapshot_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_snapshot
    ADD CONSTRAINT dataset_snapshot_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id);


--
-- Name: dataset_snapshot dataset_snapshot_parent_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_snapshot
    ADD CONSTRAINT dataset_snapshot_parent_snapshot_id_fkey FOREIGN KEY (parent_snapshot_id) REFERENCES public.dataset_snapshot(id);


--
-- Name: dataset_snapshot_sample_ordinal dataset_snapshot_sample_ordinal_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_snapshot_sample_ordinal
    ADD CONSTRAINT dataset_snapshot_sample_ordinal_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.dataset_snapshot(id);


--
-- Name: dispatch_outbox dispatch_outbox_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dispatch_outbox
    ADD CONSTRAINT dispatch_outbox_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.step(id);


--
-- Name: loop fk_loop_branch_id_branch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loop
    ADD CONSTRAINT fk_loop_branch_id_branch FOREIGN KEY (branch_id) REFERENCES public.branch(id);


--
-- Name: loop fk_loop_last_confirmed_commit_id_commit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loop
    ADD CONSTRAINT fk_loop_last_confirmed_commit_id_commit FOREIGN KEY (last_confirmed_commit_id) REFERENCES public.commit(id);


--
-- Name: loop fk_loop_project_id_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loop
    ADD CONSTRAINT fk_loop_project_id_project FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: model fk_model_created_by_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model
    ADD CONSTRAINT fk_model_created_by_user FOREIGN KEY (created_by) REFERENCES public."user"(id);


--
-- Name: model fk_model_parent_model_id_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model
    ADD CONSTRAINT fk_model_parent_model_id_model FOREIGN KEY (parent_model_id) REFERENCES public.model(id);


--
-- Name: model fk_model_project_id_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model
    ADD CONSTRAINT fk_model_project_id_project FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: model fk_model_source_commit_id_commit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model
    ADD CONSTRAINT fk_model_source_commit_id_commit FOREIGN KEY (source_commit_id) REFERENCES public.commit(id);


--
-- Name: round fk_round_input_commit_id_commit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT fk_round_input_commit_id_commit FOREIGN KEY (input_commit_id) REFERENCES public.commit(id);


--
-- Name: round fk_round_loop_id_loop; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT fk_round_loop_id_loop FOREIGN KEY (loop_id) REFERENCES public.loop(id);


--
-- Name: round fk_round_output_commit_id_commit; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT fk_round_output_commit_id_commit FOREIGN KEY (output_commit_id) REFERENCES public.commit(id);


--
-- Name: round fk_round_project_id_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round
    ADD CONSTRAINT fk_round_project_id_project FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: import_task_event import_task_event_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event
    ADD CONSTRAINT import_task_event_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.import_task(id);


--
-- Name: label label_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.label
    ADD CONSTRAINT label_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: project_dataset project_dataset_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dataset
    ADD CONSTRAINT project_dataset_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id);


--
-- Name: project_dataset project_dataset_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dataset
    ADD CONSTRAINT project_dataset_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: resource_member resource_member_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT resource_member_created_by_fkey FOREIGN KEY (created_by) REFERENCES public."user"(id);


--
-- Name: resource_member resource_member_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT resource_member_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id);


--
-- Name: resource_member resource_member_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT resource_member_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public."user"(id);


--
-- Name: resource_member resource_member_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_member
    ADD CONSTRAINT resource_member_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: role_permission role_permission_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id);


--
-- Name: round_dataset_view round_dataset_view_loop_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_dataset_view
    ADD CONSTRAINT round_dataset_view_loop_id_fkey FOREIGN KEY (loop_id) REFERENCES public.loop(id);


--
-- Name: round_dataset_view round_dataset_view_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_dataset_view
    ADD CONSTRAINT round_dataset_view_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.round(id);


--
-- Name: round_dataset_view round_dataset_view_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_dataset_view
    ADD CONSTRAINT round_dataset_view_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.dataset_snapshot(id);


--
-- Name: round_sample_metric round_sample_metric_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_sample_metric
    ADD CONSTRAINT round_sample_metric_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.round(id);


--
-- Name: round_sample_metric round_sample_metric_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.round_sample_metric
    ADD CONSTRAINT round_sample_metric_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: sample sample_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample
    ADD CONSTRAINT sample_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id);


--
-- Name: step_candidate_item step_candidate_item_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_candidate_item
    ADD CONSTRAINT step_candidate_item_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id);


--
-- Name: step_candidate_item step_candidate_item_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_candidate_item
    ADD CONSTRAINT step_candidate_item_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.step(id);


--
-- Name: step_event step_event_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_event
    ADD CONSTRAINT step_event_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.step(id);


--
-- Name: step step_input_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT step_input_commit_id_fkey FOREIGN KEY (input_commit_id) REFERENCES public.commit(id);


--
-- Name: step_metric_point step_metric_point_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step_metric_point
    ADD CONSTRAINT step_metric_point_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.step(id);


--
-- Name: step step_output_commit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT step_output_commit_id_fkey FOREIGN KEY (output_commit_id) REFERENCES public.commit(id);


--
-- Name: step step_round_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT step_round_id_fkey FOREIGN KEY (round_id) REFERENCES public.round(id);


--
-- Name: step step_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.step
    ADD CONSTRAINT step_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.dataset_snapshot(id);


--
-- Name: system_setting system_setting_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting
    ADD CONSTRAINT system_setting_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public."user"(id);


--
-- Name: user_system_role user_system_role_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_system_role
    ADD CONSTRAINT user_system_role_created_by_fkey FOREIGN KEY (created_by) REFERENCES public."user"(id);


--
-- Name: user_system_role user_system_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_system_role
    ADD CONSTRAINT user_system_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id);


--
-- Name: user_system_role user_system_role_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_system_role
    ADD CONSTRAINT user_system_role_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public."user"(id);


--
-- Name: user_system_role user_system_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_system_role
    ADD CONSTRAINT user_system_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- PostgreSQL database dump complete
--


