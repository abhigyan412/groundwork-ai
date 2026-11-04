-- Groundwork schema. Idempotent: applied on every API start (app/db/pool.py).
-- See docs/data-model.md. Every tenant-owned table carries org_id.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email          text NOT NULL,
    password_hash  text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
-- Emails are unique case-insensitively (the app also stores them lower-cased).
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email));
CREATE INDEX IF NOT EXISTS users_org_id_idx ON users (org_id);

CREATE TABLE IF NOT EXISTS assistants (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    token_hash       text NOT NULL UNIQUE,   -- SHA-256 hex; the only column used for lookup
    token_encrypted  text NOT NULL,          -- Fernet ciphertext, for re-display only (ADR 0007)
    token_prefix     text NOT NULL,          -- first chars, for display/logs
    created_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at       timestamptz
);
-- At most one active assistant per organization.
CREATE UNIQUE INDEX IF NOT EXISTS assistants_one_active_per_org
    ON assistants (org_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    filename      text NOT NULL,
    storage_path  text NOT NULL,
    size_bytes    integer NOT NULL CHECK (size_bytes >= 0),
    page_count    integer CHECK (page_count >= 0),
    status        text NOT NULL DEFAULT 'processing'
                  CHECK (status IN ('processing', 'ready', 'failed')),
    error         text,
    pages_without_text integer[] NOT NULL DEFAULT '{}',  -- flagged, not OCR'd
    generation    integer NOT NULL DEFAULT 1,  -- bumped on replace; stale processing results are discarded
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
-- Columns added after task 01 (keeps existing dev databases in step).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS pages_without_text integer[] NOT NULL DEFAULT '{}';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS generation integer NOT NULL DEFAULT 1;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS documents_org_id_idx ON documents (org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page         integer NOT NULL CHECK (page >= 1),
    text         text NOT NULL,
    embedding    vector(384) NOT NULL,      -- BAAI/bge-small-en-v1.5 (Settings.embedding_dim)
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_org_id_idx ON chunks (org_id);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS questions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    question     text NOT NULL,
    -- NULL when the question was stopped at the groundedness gate (never routed).
    route        text CHECK (route IN ('direct', 'procedural', 'policy', 'decision', 'comparison')),
    outcome      text NOT NULL CHECK (outcome IN ('answered', 'unanswered', 'needs_info', 'review')),
    answer       text NOT NULL,
    verdicts     jsonb NOT NULL DEFAULT '[]'::jsonb,
    "references" jsonb NOT NULL DEFAULT '[]'::jsonb,  -- quoted: REFERENCES is a reserved word
    timings_ms   jsonb NOT NULL DEFAULT '{}'::jsonb,
    llm_usage    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {input_tokens, output_tokens, calls, model}
    latency_ms   integer,
    created_at   timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE questions ADD COLUMN IF NOT EXISTS llm_usage jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS questions_org_created_idx ON questions (org_id, created_at DESC);
