# Stet

> Security-first correction layer for AI systems — immutable facts that LLMs can't forget.

[![Tests](https://img.shields.io/badge/tests-13%2F13%20passing-success)](https://github.com/keithrawlingsbrown/stet)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)

---

## The Problem

AI chatbots lose critical user corrections during context summarization:

**Scenario:**
- User: *"I'm allergic to peanuts"*
- Bot: ✅ Acknowledges
- [100 messages later, context gets summarized]
- Bot: ❌ Suggests peanut butter recipe

**Real-world impact:**
- Medical incidents (allergies, contraindications)
- Compliance violations (GDPR, consent management)
- Support escalations (repeated corrections)
- Trust erosion (users stop correcting the bot)

**Cost:** $5K - $5M per incident depending on severity

---

## The Solution

Stet guarantees corrections persist with **database-enforced invariants**:

✅ **Immutable** - No silent overwrites
✅ **Permission-first** - No RAG bugs from post-filtering
✅ **Auto-superseding** - One ACTIVE correction per field
✅ **GDPR-safe** - Compliant revocation with audit trails
✅ **Multi-tenant** - Isolated by design

**Key insight:** Guarantees enforced at the database layer, not application logic.

---

## Quick Start
```bash
# Clone and run
git clone https://github.com/keithrawlingsbrown/stet.git
cd stet
docker compose up --build
```

**Access:**
- API: http://127.0.0.1:8000/docs
- Postgres: localhost:5432

**Run tests:**
```bash
docker compose exec api pytest -v
```

**Expected:** 9/9 tests passing in ~0.6s

---

## Platform-Specific Notes

### Windows (Docker Desktop)

**Issue:** Docker Desktop's localhost proxy strips HTTP request paths on Windows, causing requests to fail.

**Symptom:**
```powershell
# This FAILS on Windows:
Invoke-RestMethod -Uri "http://localhost:8000/health"
# Error: "The underlying connection was closed"
```

**Workaround:** Use `127.0.0.1` instead of `localhost`:
```powershell
# This WORKS on Windows:
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

**Why this happens:** Docker Desktop on Windows uses a localhost proxy that has a known bug where HTTP paths (e.g., `/health`) are stripped from requests, causing the API to receive `GET /` instead of `GET /health`.

**Verification:**
```powershell
# Test health endpoint
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
# Expected output: status
#                  ------
#                  ok

# Test API docs
Start-Process "http://127.0.0.1:8000/docs"
```

**Note:** This is a Docker Desktop bug, not a Stet issue. The workaround is permanent until Docker fixes their localhost proxy on Windows.

---

## API Overview

### POST /v1/corrections
Create an immutable correction. Automatically supersedes any existing ACTIVE correction for the same field.
```bash
curl -X POST http://127.0.0.1:8000/v1/corrections \
  -H "X-Tenant-Id: <uuid>" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": {"type": "user", "id": "user_123"},
    "field_key": "medical.allergy",
    "value": "peanuts",
    "class": "FACT",
    "permissions": {"readers": ["bot:support_v2"]},
    "actor": {"type": "user", "id": "user_123"},
    "idempotency_key": "<uuid>"
  }'
```

**Response (201):**
```json
{
  "correction_id": "...",
  "status": "ACTIVE",
  "supersedes": null,
  "created_at": "2025-12-21T..."
}
```

### GET /v1/facts
Retrieve ACTIVE corrections with permission filtering applied **before** recall.
```bash
curl "http://127.0.0.1:8000/v1/facts?subject_type=user&subject_id=user_123&requester_id=bot:support_v2" \
  -H "X-Tenant-Id: <uuid>"
```

**Response (200):**
```json
{
  "subject": {"type": "user", "id": "user_123"},
  "facts": [
    {
      "field_key": "medical.allergy",
      "value": "peanuts",
      "corrected_at": "2025-12-21T...",
      "correction_id": "...",
      "actor": {"type": "user", "id": "user_123"}
    }
  ]
}
```

### GET /v1/history
Audit trail showing ACTIVE + SUPERSEDED corrections (REVOKED excluded by default).
```bash
curl "http://127.0.0.1:8000/v1/history?subject_type=user&subject_id=user_123&requester_id=bot:support_v2" \
  -H "X-Tenant-Id: <uuid>"
```

---

## Architecture

### Core Guarantees

**1. Immutable Corrections**
- No in-place updates
- New correction → supersedes old
- Audit trail preserved

**2. Permission-First Recall**
```
Query → Filter by permissions → Return results
```
**Not:**
```
Query → Return all → Filter afterwards  ← RAG Bug!
```

**3. Database-Enforced Invariants**
```sql
CREATE UNIQUE INDEX uniq_active_per_field
ON corrections (tenant_id, subject_type, subject_id, field_key)
WHERE status = 'ACTIVE';
```
Only one ACTIVE correction per field — enforced by Postgres, not app logic.

**4. FACT vs DISCARDABLE**
- `FACT`: Permanent, never compacted
- `DISCARDABLE`: Can be removed during summarization

**5. GDPR-Safe Revocation**
- Status: `ACTIVE` → `SUPERSEDED` → `REVOKED`
- REVOKED excluded from `/facts` automatically
- Visible in `/history?include_revoked=true` for compliance

### Tech Stack

- **API:** FastAPI + Pydantic v2
- **Database:** Postgres 15 + asyncpg
- **Deployment:** Docker Compose
- **Tests:** pytest + pytest-asyncio

### Data Model
```
corrections
├── correction_id (UUID, PK)
├── tenant_id (UUID, indexed)
├── subject (type, id)
├── field_key (TEXT)
├── value (JSONB)
├── class (FACT | DISCARDABLE)
├── status (ACTIVE | SUPERSEDED | REVOKED)
├── supersedes (UUID, nullable)
├── permissions (JSONB)
├── actor (type, id)
├── idempotency_key (TEXT)
├── origin (JSONB)
└── created_at (TIMESTAMPTZ)

idempotency
├── tenant_id (UUID)
├── key (TEXT)
├── correction_id (UUID)
└── payload_hash (TEXT, SHA-256)

enforcement_heartbeats
├── heartbeat_id (UUID, PK)
├── tenant_id (UUID, indexed)
├── system_id (TEXT)
├── enforced_correction_version (TIMESTAMPTZ)
├── origin (JSONB)
└── reported_at (TIMESTAMPTZ)
```

---

## Test Coverage

**9/9 conformance tests prove all guarantees:**
```bash
docker compose exec api pytest -v
```
```
tests/test_corrections_write.py
  ✅ test_create_correction_basic       - Immutable creation
  ✅ test_automatic_superseding         - v1→v2 chain tracking
  ✅ test_idempotency_retry             - Safe retries (same payload)
  ✅ test_idempotency_conflict          - Conflict detection (different payload)

tests/test_facts_read.py
  ✅ test_permission_first              - Permission filtering before recall
  ✅ test_fact_only                     - DISCARDABLE excluded from /facts
  ✅ test_cross_subject_isolation       - Multi-subject isolation

tests/test_history_read.py
  ✅ test_history_chain                 - Audit trail (ACTIVE + SUPERSEDED)
  ✅ test_revoked_handling              - GDPR compliance (REVOKED exclusion)

======================== 9 passed in 0.60s ========================
```

---

## Use Cases

**1. Medical AI Assistants**
- Allergies, contraindications, consent
- HIPAA compliance required
- Cost of error: patient harm

**2. Customer Support Bots**
- Do-not-contact preferences
- Account cancellations
- Privacy requests (GDPR Article 17)

**3. Financial Advisory Bots**
- Risk tolerance, investment restrictions
- Regulatory compliance (FINRA, SEC)
- Audit trail requirements

**4. HR/Recruiting Bots**
- Candidate preferences, salary expectations
- EEOC compliance, bias prevention
- Legal holds on data deletion

---

## Design Philosophy

**What Stet is:**
- ✅ Correction storage with enforceable guarantees
- ✅ Permission-aware recall layer
- ✅ GDPR-compliant data lifecycle

**What Stet is NOT:**
- ❌ Vector database (use Pinecone/Weaviate for embeddings)
- ❌ LLM context manager (use LangChain/LlamaIndex for that)
- ❌ Full memory system (corrections are facts, not conversations)

**Integration pattern:**
```
User input → LLM → Correction detected → POST /v1/corrections
Next turn → GET /v1/facts → Inject into prompt → LLM responds
```

---

## Deployment

### Development
```bash
docker compose up --build
```

### Production (Example: DigitalOcean)
```bash
# 1. Provision VPS (2 vCPU, 4GB RAM)
# 2. Clone repo
git clone https://github.com/keithrawlingsbrown/stet.git
cd stet

# 3. Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost/stet"

# 4. Run with Docker
docker compose -f docker-compose.prod.yml up -d

# 5. Setup TLS (Let's Encrypt)
# 6. Configure backup cron job
```

**Estimated cost:** $20-50/month for pilot (1-5 customers)

---

## Roadmap

**v1.0 (Current)** ✅
- Core API (corrections, facts, history)
- Conformance tests (9/9 passing)
- Docker deployment
- Origin attestation (forensic-grade attribution)
- Enforcement heartbeat tracking

**v1.1 (Next)**
- Rate limiting (Redis token bucket)
- Metrics/monitoring (Prometheus)
- Migration tooling
- Drift detection (Phase 3 Step 3)

**v1.2 (Future)**
- Explicit superseding (specify target)
- Batch operations
- Webhook notifications

**v2.0 (Exploratory)**
- Change data capture (CDC)
- Read replicas
- Multi-region support

---

## Contributing

**This is a solo project built for DevSecOps portfolio purposes.**

If you find bugs or have suggestions:
1. Open an issue with reproduction steps
2. Include test case if possible
3. No PRs accepted at this time

---

## License

MIT License - see [LICENSE](LICENSE) for details

---

## Author

**Keith Rawlings-Brown**
Building in public to practice real DevSecOps engineering.

**Why build this?**
- Prove I can design enforceable guarantees (not just implement features)
- Practice security-first architecture (shift-left, policy-as-code)
- Create portfolio artifact for platform/DevSecOps roles

**Connect:**
- GitHub: [@keithrawlingsbrown](https://github.com/keithrawlingsbrown)
- LinkedIn: [linkedin.com/in/keithrawlingsbrown](https://linkedin.com/in/keithrawlingsbrown)

---

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [asyncpg](https://github.com/MagicStack/asyncpg) - Fast PostgreSQL driver
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [pytest](https://pytest.org/) - Testing framework

Inspired by:
- Event sourcing patterns (immutability)
- OAuth2 permission models (scopes + deny-lists)
- GDPR Article 17 (right to erasure)

---

**Status:** Production-ready for pilot deployments
**Last updated:** December 2025



