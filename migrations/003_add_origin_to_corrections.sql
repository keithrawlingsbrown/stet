-- Migration: Add origin column to corrections table
-- Purpose: Forensic-grade attribution for every correction write

ALTER TABLE corrections 
ADD COLUMN origin JSONB NOT NULL DEFAULT '{"service": "unknown", "version": "unknown", "environment": "unknown"}';

-- Remove default after backfill
ALTER TABLE corrections 
ALTER COLUMN origin DROP DEFAULT;

COMMENT ON COLUMN corrections.origin IS 'Origin attestation: service identity, version, and environment for forensic attribution.';
