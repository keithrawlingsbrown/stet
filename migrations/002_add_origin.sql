-- Migration: Add origin attestation column
-- Purpose: Forensic-grade attribution for every correction write

ALTER TABLE corrections 
ADD COLUMN origin JSONB NOT NULL DEFAULT '{"service": "unknown", "version": "unknown", "environment": "unknown"}';

-- Remove the default after adding (so future inserts MUST provide origin)
ALTER TABLE corrections 
ALTER COLUMN origin DROP DEFAULT;

COMMENT ON COLUMN corrections.origin IS 'Origin attestation: service identity, version, and environment. Required for forensic attribution.';
