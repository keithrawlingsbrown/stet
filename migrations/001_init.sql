CREATE TABLE IF NOT EXISTS corrections (
    correction_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value JSONB NOT NULL,
    class TEXT CHECK (class IN ('FACT', 'DISCARDABLE')) NOT NULL,
    status TEXT CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'REVOKED')) NOT NULL,
    supersedes UUID,
    permissions JSONB NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_per_field
ON corrections (tenant_id, subject_type, subject_id, field_key)
WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_active_facts
ON corrections (tenant_id, subject_type, subject_id)
WHERE status = 'ACTIVE' AND class = 'FACT';

CREATE TABLE IF NOT EXISTS idempotency (
    tenant_id UUID NOT NULL,
    key TEXT NOT NULL,
    correction_id UUID NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, key)
);
