# Stet Architecture

## Core Guarantees
1. Immutable corrections (no overwrites)
2. Permission-first recall (no RAG bugs)
3. FACT vs DISCARDABLE separation
4. Database-enforced invariants
5. GDPR-safe REVOKED handling

## API Endpoints
- POST /v1/corrections - Create immutable correction
- GET /v1/facts - Retrieve ACTIVE FACT corrections
- GET /v1/history - Audit trail

See full spec in Copilot instructions.
