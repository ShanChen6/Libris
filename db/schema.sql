\restrict dbmate

-- Dumped from database version 17.8 (Debian 17.8-1.pgdg12+1)
-- Dumped by pg_dump version 18.7

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: document_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.document_status AS ENUM (
    'ACTIVE',
    'AMENDED',
    'EXPIRED',
    'PENDING'
);


--
-- Name: message_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.message_role AS ENUM (
    'user',
    'assistant',
    'system'
);


--
-- Name: user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.user_role AS ENUM (
    'USER',
    'ADMIN'
);


--
-- Name: recompute_document_status(date); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.recompute_document_status(as_of date DEFAULT CURRENT_DATE) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
  changed integer;
BEGIN
  WITH computed AS (
    SELECT d.id,
      (SELECT min(r.effective_date) FROM document_relations r
        WHERE r.target_number = d.document_number AND r.relation_type = 'replaces'
          AND r.effective_date <= as_of) AS expiry,
      EXISTS (SELECT 1 FROM document_relations r
        WHERE r.target_number = d.document_number AND r.relation_type IN ('amends', 'repeals_part')
          AND r.effective_date <= as_of)
      OR EXISTS (SELECT 1 FROM superseded_provisions sp
        WHERE sp.target_number = d.document_number AND sp.effective_date <= as_of) AS amended
    FROM legal_documents d
  ), next AS (
    SELECT c.id, c.expiry,
      CASE
        WHEN d.effective_date > as_of THEN 'PENDING'
        WHEN c.expiry IS NOT NULL THEN 'EXPIRED'
        WHEN c.amended THEN 'AMENDED'
        ELSE 'ACTIVE'
      END::document_status AS status
    FROM computed c JOIN legal_documents d ON d.id = c.id
  )
  UPDATE legal_documents d
     SET status = n.status, expiry_date = n.expiry, status_as_of = as_of
    FROM next n
   WHERE d.id = n.id
     AND (d.status, d.expiry_date, d.status_as_of) IS DISTINCT FROM (n.status, n.expiry, as_of);
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    role public.message_role NOT NULL,
    content text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    title text,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_relations (
    source_number text NOT NULL,
    target_number text NOT NULL,
    relation_type text NOT NULL,
    effective_date date,
    evidence text NOT NULL,
    CONSTRAINT document_relations_relation_type_check CHECK ((relation_type = ANY (ARRAY['replaces'::text, 'repeals_part'::text, 'amends'::text, 'sets_effective_date'::text])))
);


--
-- Name: ingestion_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingestion_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    step text,
    filename text NOT NULL,
    content_type text,
    size_bytes integer NOT NULL,
    sha256 text NOT NULL,
    document_number text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    document_id uuid,
    chunks integer,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    error text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    CONSTRAINT ingestion_jobs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'processing'::text, 'done'::text, 'failed'::text])))
);


--
-- Name: legal_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_chunks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    part text,
    chapter text,
    section text,
    article text,
    article_title text,
    clause text,
    point text,
    context_prefix text NOT NULL,
    content text NOT NULL,
    char_start integer NOT NULL,
    char_end integer NOT NULL,
    token_count integer,
    embedding public.vector(1024),
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, ((context_prefix || ' '::text) || content))) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_chunks_char_start_check CHECK ((char_start >= 0)),
    CONSTRAINT legal_chunks_check CHECK ((char_end > char_start))
);


--
-- Name: legal_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_number text NOT NULL,
    document_type text,
    title text NOT NULL,
    issuing_body text,
    signer text,
    issue_date date,
    effective_date date,
    expiry_date date,
    status public.document_status DEFAULT 'ACTIVE'::public.document_status NOT NULL,
    status_as_of date,
    full_text text NOT NULL,
    needs_review boolean DEFAULT false NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    source_url text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT legal_documents_check CHECK (((expiry_date IS NULL) OR (effective_date IS NULL) OR (expiry_date >= effective_date)))
);


--
-- Name: message_citations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_citations (
    message_id uuid NOT NULL,
    "position" integer NOT NULL,
    chunk_id uuid,
    document_id uuid,
    document_number text NOT NULL,
    label text NOT NULL,
    quote text,
    score real
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: superseded_provisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.superseded_provisions (
    target_number text NOT NULL,
    article text NOT NULL,
    clause text DEFAULT ''::text NOT NULL,
    kind text NOT NULL,
    source_number text NOT NULL,
    effective_date date,
    evidence text NOT NULL,
    CONSTRAINT superseded_provisions_kind_check CHECK ((kind = ANY (ARRAY['repealed'::text, 'amended'::text])))
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    full_name text,
    role public.user_role DEFAULT 'USER'::public.user_role NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: document_relations document_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_relations
    ADD CONSTRAINT document_relations_pkey PRIMARY KEY (source_number, target_number, relation_type);


--
-- Name: ingestion_jobs ingestion_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_pkey PRIMARY KEY (id);


--
-- Name: legal_chunks legal_chunks_document_id_chunk_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_chunks
    ADD CONSTRAINT legal_chunks_document_id_chunk_index_key UNIQUE (document_id, chunk_index);


--
-- Name: legal_chunks legal_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_chunks
    ADD CONSTRAINT legal_chunks_pkey PRIMARY KEY (id);


--
-- Name: legal_documents legal_documents_document_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_document_number_key UNIQUE (document_number);


--
-- Name: legal_documents legal_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_pkey PRIMARY KEY (id);


--
-- Name: legal_documents legal_documents_source_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_source_source_id_key UNIQUE (source, source_id);


--
-- Name: message_citations message_citations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_citations
    ADD CONSTRAINT message_citations_pkey PRIMARY KEY (message_id, "position");


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: superseded_provisions superseded_provisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superseded_provisions
    ADD CONSTRAINT superseded_provisions_pkey PRIMARY KEY (target_number, article, clause, source_number);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: chat_messages_session_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_messages_session_idx ON public.chat_messages USING btree (session_id, created_at);


--
-- Name: chat_sessions_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_sessions_user_idx ON public.chat_sessions USING btree (user_id, updated_at DESC);


--
-- Name: document_relations_target_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_relations_target_idx ON public.document_relations USING btree (target_number);


--
-- Name: ingestion_jobs_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ingestion_jobs_created_idx ON public.ingestion_jobs USING btree (created_at DESC);


--
-- Name: legal_chunks_document_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX legal_chunks_document_idx ON public.legal_chunks USING btree (document_id, chunk_index);


--
-- Name: legal_chunks_embedding_hnsw_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX legal_chunks_embedding_hnsw_idx ON public.legal_chunks USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: legal_chunks_search_vector_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX legal_chunks_search_vector_idx ON public.legal_chunks USING gin (search_vector);


--
-- Name: legal_documents_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX legal_documents_status_idx ON public.legal_documents USING btree (status);


--
-- Name: legal_documents_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX legal_documents_type_idx ON public.legal_documents USING btree (document_type);


--
-- Name: message_citations_chunk_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX message_citations_chunk_idx ON public.message_citations USING btree (chunk_id);


--
-- Name: users_email_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX users_email_key ON public.users USING btree (lower(email));


--
-- Name: chat_sessions chat_sessions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER chat_sessions_updated_at BEFORE UPDATE ON public.chat_sessions FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: legal_documents legal_documents_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER legal_documents_updated_at BEFORE UPDATE ON public.legal_documents FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: users users_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: chat_messages chat_messages_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE;


--
-- Name: chat_sessions chat_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: ingestion_jobs ingestion_jobs_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ingestion_jobs ingestion_jobs_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingestion_jobs
    ADD CONSTRAINT ingestion_jobs_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.legal_documents(id) ON DELETE SET NULL;


--
-- Name: legal_chunks legal_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_chunks
    ADD CONSTRAINT legal_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.legal_documents(id) ON DELETE CASCADE;


--
-- Name: message_citations message_citations_chunk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_citations
    ADD CONSTRAINT message_citations_chunk_id_fkey FOREIGN KEY (chunk_id) REFERENCES public.legal_chunks(id) ON DELETE SET NULL;


--
-- Name: message_citations message_citations_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_citations
    ADD CONSTRAINT message_citations_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.legal_documents(id) ON DELETE SET NULL;


--
-- Name: message_citations message_citations_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_citations
    ADD CONSTRAINT message_citations_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.chat_messages(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20261123000001'),
    ('20261123000002'),
    ('20261123000003'),
    ('20261123000004'),
    ('20261123000005'),
    ('20261123000006'),
    ('20261123000007');
