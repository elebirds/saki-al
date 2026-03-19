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
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: access_principal_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.access_principal_status AS ENUM (
    'active',
    'disabled'
);


--
-- Name: agent_command_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_command_status AS ENUM (
    'pending',
    'claimed',
    'acked',
    'finished',
    'failed',
    'expired'
);


--
-- Name: agent_command_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_command_type AS ENUM (
    'assign',
    'cancel'
);


--
-- Name: agent_transport_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_transport_mode AS ENUM (
    'direct',
    'pull',
    'relay'
);


--
-- Name: asset_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_kind AS ENUM (
    'image',
    'video',
    'archive',
    'document',
    'binary'
);


--
-- Name: asset_owner_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_owner_type AS ENUM (
    'project',
    'dataset',
    'sample'
);


--
-- Name: asset_reference_lifecycle; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_reference_lifecycle AS ENUM (
    'durable'
);


--
-- Name: asset_reference_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_reference_role AS ENUM (
    'attachment',
    'primary'
);


--
-- Name: asset_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_status AS ENUM (
    'pending_upload',
    'ready'
);


--
-- Name: asset_storage_backend; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_storage_backend AS ENUM (
    'minio'
);


--
-- Name: asset_upload_intent_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_upload_intent_state AS ENUM (
    'initiated',
    'completed',
    'canceled',
    'expired'
);


--
-- Name: import_task_event_phase; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.import_task_event_phase AS ENUM (
    'prepare',
    'project_annotations_execute',
    'apply_annotations'
);


--
-- Name: import_task_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.import_task_status AS ENUM (
    'queued',
    'running',
    'completed',
    'failed'
);


--
-- Name: import_upload_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.import_upload_session_status AS ENUM (
    'initiated',
    'completed',
    'aborted'
);


--
-- Name: runtime_executor_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_executor_status AS ENUM (
    'online'
);


--
-- Name: runtime_task_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_task_kind AS ENUM (
    'PREDICTION'
);


--
-- Name: runtime_task_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_task_status AS ENUM (
    'pending',
    'assigned',
    'running',
    'cancel_requested',
    'succeeded',
    'failed',
    'canceled'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_permission_grant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_permission_grant (
    principal_id uuid NOT NULL,
    permission text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: access_principal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_principal (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    subject_type text NOT NULL,
    subject_key text NOT NULL,
    display_name text NOT NULL,
    status public.access_principal_status DEFAULT 'active'::public.access_principal_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent (
    id text NOT NULL,
    version text NOT NULL,
    capabilities text[] DEFAULT '{}'::text[] NOT NULL,
    transport_mode public.agent_transport_mode NOT NULL,
    control_base_url text,
    max_concurrency integer DEFAULT 1 NOT NULL,
    running_task_ids text[] DEFAULT '{}'::text[] NOT NULL,
    status text DEFAULT 'online'::text NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_command; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_command (
    command_id uuid NOT NULL,
    agent_id text NOT NULL,
    task_id uuid NOT NULL,
    assignment_id bigint NOT NULL,
    command_type public.agent_command_type NOT NULL,
    transport_mode public.agent_transport_mode NOT NULL,
    status public.agent_command_status DEFAULT 'pending'::public.agent_command_status NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    expire_at timestamp with time zone NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    claim_token uuid,
    claim_until timestamp with time zone,
    acked_at timestamp with time zone,
    finished_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: annotation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    group_id text NOT NULL,
    label_id text NOT NULL,
    view text NOT NULL,
    annotation_type text NOT NULL,
    geometry jsonb NOT NULL,
    attrs jsonb DEFAULT '{}'::jsonb NOT NULL,
    source text NOT NULL,
    is_generated boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: asset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    kind public.asset_kind NOT NULL,
    status public.asset_status DEFAULT 'pending_upload'::public.asset_status NOT NULL,
    storage_backend public.asset_storage_backend NOT NULL,
    bucket text NOT NULL,
    object_key text NOT NULL,
    content_type text DEFAULT ''::text NOT NULL,
    size_bytes bigint DEFAULT 0 NOT NULL,
    sha256_hex text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by uuid,
    ready_at timestamp with time zone,
    orphaned_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: asset_reference; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_reference (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    asset_id uuid NOT NULL,
    owner_type public.asset_owner_type NOT NULL,
    owner_id uuid NOT NULL,
    role public.asset_reference_role NOT NULL,
    lifecycle public.asset_reference_lifecycle DEFAULT 'durable'::public.asset_reference_lifecycle NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: asset_upload_intent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_upload_intent (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    asset_id uuid NOT NULL,
    owner_type public.asset_owner_type NOT NULL,
    owner_id uuid NOT NULL,
    role public.asset_reference_role NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    declared_content_type text NOT NULL,
    state public.asset_upload_intent_state DEFAULT 'initiated'::public.asset_upload_intent_state NOT NULL,
    idempotency_key text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_by uuid,
    completed_at timestamp with time zone,
    canceled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: goose_db_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.goose_db_version (
    id integer NOT NULL,
    version_id bigint NOT NULL,
    is_applied boolean NOT NULL,
    tstamp timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: goose_db_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.goose_db_version ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.goose_db_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: import_preview_manifest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_preview_manifest (
    token text NOT NULL,
    mode text NOT NULL,
    project_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    upload_session_id uuid NOT NULL,
    manifest jsonb NOT NULL,
    params_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: import_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_task (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    mode text NOT NULL,
    resource_type text NOT NULL,
    resource_id uuid NOT NULL,
    status public.import_task_status DEFAULT 'queued'::public.import_task_status NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    result jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: import_task_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_task_event (
    seq bigint NOT NULL,
    task_id uuid NOT NULL,
    event text NOT NULL,
    phase public.import_task_event_phase NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: import_task_event_seq_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.import_task_event_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_task_event_seq_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.import_task_event_seq_seq OWNED BY public.import_task_event.seq;


--
-- Name: import_upload_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_upload_session (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    mode text NOT NULL,
    file_name text NOT NULL,
    object_key text NOT NULL,
    content_type text DEFAULT ''::text NOT NULL,
    status public.import_upload_session_status DEFAULT 'initiated'::public.import_upload_session_status NOT NULL,
    completed_at timestamp with time zone,
    aborted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project (
    id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: project_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_dataset (
    project_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_executor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_executor (
    id text NOT NULL,
    version text NOT NULL,
    capabilities text[] DEFAULT '{}'::text[] NOT NULL,
    status public.runtime_executor_status DEFAULT 'online'::public.runtime_executor_status NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_lease; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_lease (
    name text NOT NULL,
    holder text NOT NULL,
    epoch bigint NOT NULL,
    lease_until timestamp with time zone NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_outbox (
    id bigint NOT NULL,
    topic text NOT NULL,
    aggregate_type text DEFAULT 'task'::text NOT NULL,
    aggregate_id text NOT NULL,
    idempotency_key text NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: runtime_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.runtime_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: runtime_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.runtime_outbox_id_seq OWNED BY public.runtime_outbox.id;


--
-- Name: runtime_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_task (
    id uuid NOT NULL,
    task_kind public.runtime_task_kind DEFAULT 'PREDICTION'::public.runtime_task_kind NOT NULL,
    task_type text NOT NULL,
    status public.runtime_task_status DEFAULT 'pending'::public.runtime_task_status NOT NULL,
    assigned_agent_id text,
    current_execution_id text,
    attempt integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 1 NOT NULL,
    resolved_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    depends_on_task_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    leader_epoch bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sample; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_id uuid NOT NULL,
    name text DEFAULT ''::text NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sample_match_ref; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_match_ref (
    id bigint NOT NULL,
    dataset_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    ref_type text NOT NULL,
    ref_value text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sample_match_ref_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sample_match_ref_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sample_match_ref_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sample_match_ref_id_seq OWNED BY public.sample_match_ref.id;


--
-- Name: task_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_assignment (
    id bigint NOT NULL,
    task_id uuid NOT NULL,
    attempt integer NOT NULL,
    agent_id text NOT NULL,
    execution_id text NOT NULL,
    status public.runtime_task_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_assignment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_assignment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_assignment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_assignment_id_seq OWNED BY public.task_assignment.id;


--
-- Name: import_task_event seq; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event ALTER COLUMN seq SET DEFAULT nextval('public.import_task_event_seq_seq'::regclass);


--
-- Name: runtime_outbox id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_outbox ALTER COLUMN id SET DEFAULT nextval('public.runtime_outbox_id_seq'::regclass);


--
-- Name: sample_match_ref id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_match_ref ALTER COLUMN id SET DEFAULT nextval('public.sample_match_ref_id_seq'::regclass);


--
-- Name: task_assignment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment ALTER COLUMN id SET DEFAULT nextval('public.task_assignment_id_seq'::regclass);


--
-- Name: access_permission_grant access_permission_grant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_permission_grant
    ADD CONSTRAINT access_permission_grant_pkey PRIMARY KEY (principal_id, permission);


--
-- Name: access_principal access_principal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_principal
    ADD CONSTRAINT access_principal_pkey PRIMARY KEY (id);


--
-- Name: access_principal access_principal_subject_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_principal
    ADD CONSTRAINT access_principal_subject_unique UNIQUE (subject_type, subject_key);


--
-- Name: agent_command agent_command_claim_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_command
    ADD CONSTRAINT agent_command_claim_token_key UNIQUE (claim_token);


--
-- Name: agent_command agent_command_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_command
    ADD CONSTRAINT agent_command_pkey PRIMARY KEY (command_id);


--
-- Name: agent agent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent
    ADD CONSTRAINT agent_pkey PRIMARY KEY (id);


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
-- Name: asset_reference asset_reference_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_reference
    ADD CONSTRAINT asset_reference_pkey PRIMARY KEY (id);


--
-- Name: asset asset_storage_backend_bucket_object_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset
    ADD CONSTRAINT asset_storage_backend_bucket_object_key_key UNIQUE (storage_backend, bucket, object_key);


--
-- Name: asset_upload_intent asset_upload_intent_asset_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_upload_intent
    ADD CONSTRAINT asset_upload_intent_asset_id_key UNIQUE (asset_id);


--
-- Name: asset_upload_intent asset_upload_intent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_upload_intent
    ADD CONSTRAINT asset_upload_intent_pkey PRIMARY KEY (id);


--
-- Name: dataset dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset
    ADD CONSTRAINT dataset_pkey PRIMARY KEY (id);


--
-- Name: goose_db_version goose_db_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goose_db_version
    ADD CONSTRAINT goose_db_version_pkey PRIMARY KEY (id);


--
-- Name: import_preview_manifest import_preview_manifest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_preview_manifest
    ADD CONSTRAINT import_preview_manifest_pkey PRIMARY KEY (token);


--
-- Name: import_task_event import_task_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event
    ADD CONSTRAINT import_task_event_pkey PRIMARY KEY (seq);


--
-- Name: import_task import_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task
    ADD CONSTRAINT import_task_pkey PRIMARY KEY (id);


--
-- Name: import_upload_session import_upload_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_upload_session
    ADD CONSTRAINT import_upload_session_pkey PRIMARY KEY (id);


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
-- Name: runtime_executor runtime_executor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_executor
    ADD CONSTRAINT runtime_executor_pkey PRIMARY KEY (id);


--
-- Name: runtime_lease runtime_lease_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_lease
    ADD CONSTRAINT runtime_lease_pkey PRIMARY KEY (name);


--
-- Name: runtime_outbox runtime_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_outbox
    ADD CONSTRAINT runtime_outbox_pkey PRIMARY KEY (id);


--
-- Name: runtime_task runtime_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_task
    ADD CONSTRAINT runtime_task_pkey PRIMARY KEY (id);


--
-- Name: sample_match_ref sample_match_ref_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_match_ref
    ADD CONSTRAINT sample_match_ref_pkey PRIMARY KEY (id);


--
-- Name: sample sample_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample
    ADD CONSTRAINT sample_pkey PRIMARY KEY (id);


--
-- Name: task_assignment task_assignment_execution_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment
    ADD CONSTRAINT task_assignment_execution_id_key UNIQUE (execution_id);


--
-- Name: task_assignment task_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment
    ADD CONSTRAINT task_assignment_pkey PRIMARY KEY (id);


--
-- Name: task_assignment task_assignment_task_attempt_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment
    ADD CONSTRAINT task_assignment_task_attempt_key UNIQUE (task_id, attempt);


--
-- Name: agent_command_expire_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_command_expire_idx ON public.agent_command USING btree (expire_at, command_id) WHERE (status = ANY (ARRAY['pending'::public.agent_command_status, 'claimed'::public.agent_command_status, 'acked'::public.agent_command_status]));


--
-- Name: agent_command_pull_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_command_pull_due_idx ON public.agent_command USING btree (agent_id, available_at, command_id) WHERE ((status = 'pending'::public.agent_command_status) AND (transport_mode = 'pull'::public.agent_transport_mode));


--
-- Name: agent_command_push_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_command_push_due_idx ON public.agent_command USING btree (available_at, command_id) WHERE ((status = 'pending'::public.agent_command_status) AND (transport_mode = ANY (ARRAY['direct'::public.agent_transport_mode, 'relay'::public.agent_transport_mode])));


--
-- Name: agent_last_seen_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_last_seen_at_idx ON public.agent USING btree (last_seen_at DESC);


--
-- Name: asset_reference_active_asset_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX asset_reference_active_asset_idx ON public.asset_reference USING btree (asset_id) WHERE (deleted_at IS NULL);


--
-- Name: asset_reference_active_asset_owner_role_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX asset_reference_active_asset_owner_role_key ON public.asset_reference USING btree (asset_id, owner_type, owner_id, role) WHERE (deleted_at IS NULL);


--
-- Name: asset_reference_active_owner_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX asset_reference_active_owner_idx ON public.asset_reference USING btree (owner_type, owner_id) WHERE (deleted_at IS NULL);


--
-- Name: asset_reference_active_owner_role_primary_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX asset_reference_active_owner_role_primary_key ON public.asset_reference USING btree (owner_type, owner_id, role) WHERE (is_primary AND (deleted_at IS NULL));


--
-- Name: asset_upload_intent_owner_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX asset_upload_intent_owner_idx ON public.asset_upload_intent USING btree (owner_type, owner_id);


--
-- Name: asset_upload_intent_owner_role_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX asset_upload_intent_owner_role_idempotency_key ON public.asset_upload_intent USING btree (owner_type, owner_id, role, idempotency_key);


--
-- Name: asset_upload_intent_state_expires_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX asset_upload_intent_state_expires_at_idx ON public.asset_upload_intent USING btree (state, expires_at);


--
-- Name: idx_access_principal_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_access_principal_status ON public.access_principal USING btree (status, id);


--
-- Name: idx_annotation_project_sample_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_annotation_project_sample_created_at ON public.annotation USING btree (project_id, sample_id, created_at, id);


--
-- Name: idx_import_preview_manifest_upload_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_import_preview_manifest_upload_session ON public.import_preview_manifest USING btree (upload_session_id);


--
-- Name: idx_import_task_event_task_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_import_task_event_task_seq ON public.import_task_event USING btree (task_id, seq);


--
-- Name: idx_import_task_user_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_import_task_user_created_at ON public.import_task USING btree (user_id, created_at DESC);


--
-- Name: idx_import_upload_session_user_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_import_upload_session_user_created_at ON public.import_upload_session USING btree (user_id, created_at DESC);


--
-- Name: idx_sample_match_ref_exact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sample_match_ref_exact ON public.sample_match_ref USING btree (dataset_id, ref_type, ref_value, id);


--
-- Name: runtime_outbox_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX runtime_outbox_due_idx ON public.runtime_outbox USING btree (available_at, id) WHERE (published_at IS NULL);


--
-- Name: runtime_outbox_idempotency_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX runtime_outbox_idempotency_key_idx ON public.runtime_outbox USING btree (idempotency_key);


--
-- Name: task_assignment_agent_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX task_assignment_agent_created_idx ON public.task_assignment USING btree (agent_id, created_at DESC);


--
-- Name: access_permission_grant access_permission_grant_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_permission_grant
    ADD CONSTRAINT access_permission_grant_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.access_principal(id) ON DELETE CASCADE;


--
-- Name: agent_command agent_command_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_command
    ADD CONSTRAINT agent_command_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent(id);


--
-- Name: agent_command agent_command_assignment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_command
    ADD CONSTRAINT agent_command_assignment_id_fkey FOREIGN KEY (assignment_id) REFERENCES public.task_assignment(id) ON DELETE CASCADE;


--
-- Name: agent_command agent_command_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_command
    ADD CONSTRAINT agent_command_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.runtime_task(id) ON DELETE CASCADE;


--
-- Name: annotation annotation_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id) ON DELETE CASCADE;


--
-- Name: annotation annotation_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation
    ADD CONSTRAINT annotation_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id) ON DELETE CASCADE;


--
-- Name: asset_reference asset_reference_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_reference
    ADD CONSTRAINT asset_reference_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.asset(id) ON DELETE CASCADE;


--
-- Name: asset_upload_intent asset_upload_intent_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_upload_intent
    ADD CONSTRAINT asset_upload_intent_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.asset(id) ON DELETE CASCADE;


--
-- Name: import_preview_manifest import_preview_manifest_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_preview_manifest
    ADD CONSTRAINT import_preview_manifest_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id) ON DELETE CASCADE;


--
-- Name: import_preview_manifest import_preview_manifest_upload_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_preview_manifest
    ADD CONSTRAINT import_preview_manifest_upload_session_id_fkey FOREIGN KEY (upload_session_id) REFERENCES public.import_upload_session(id) ON DELETE CASCADE;


--
-- Name: import_task_event import_task_event_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_task_event
    ADD CONSTRAINT import_task_event_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.import_task(id) ON DELETE CASCADE;


--
-- Name: project_dataset project_dataset_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dataset
    ADD CONSTRAINT project_dataset_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id) ON DELETE CASCADE;


--
-- Name: project_dataset project_dataset_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dataset
    ADD CONSTRAINT project_dataset_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id) ON DELETE CASCADE;


--
-- Name: sample sample_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample
    ADD CONSTRAINT sample_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id) ON DELETE CASCADE;


--
-- Name: sample_match_ref sample_match_ref_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_match_ref
    ADD CONSTRAINT sample_match_ref_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.dataset(id) ON DELETE CASCADE;


--
-- Name: sample_match_ref sample_match_ref_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_match_ref
    ADD CONSTRAINT sample_match_ref_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.sample(id) ON DELETE CASCADE;


--
-- Name: task_assignment task_assignment_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment
    ADD CONSTRAINT task_assignment_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent(id);


--
-- Name: task_assignment task_assignment_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_assignment
    ADD CONSTRAINT task_assignment_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.runtime_task(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
