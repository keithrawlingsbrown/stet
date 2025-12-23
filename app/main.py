import json
from uuid import UUID, uuid4
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Depends, HTTPException, Query, Response
from asyncpg.exceptions import UniqueViolationError
from app.db import get_pool, close_pool
from app.models import (
    CreateCorrectionRequest, CreateCorrectionResponse,
    FactsResponse, FactItem, HistoryResponse, HistoryItem,
    Subject, Actor, CorrectionStatus, CorrectionClass,
)
from app.logic import canonical_json_sha256, parse_csv, is_allowed

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: pool created lazily by get_pool()
    yield
    # Shutdown: close pool cleanly
    await close_pool()

app = FastAPI(title="Stet API", version="1.0.0", lifespan=lifespan)

def rate_limit_headers() -> dict:
    return {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "59", "X-RateLimit-Reset": "0"}

def require_tenant(x_tenant_id: UUID = Header(..., alias="X-Tenant-Id")) -> UUID:
    return x_tenant_id

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/corrections", response_model=CreateCorrectionResponse)
async def create_correction(payload: CreateCorrectionRequest, response: Response, tenant_id: UUID = Depends(require_tenant)):
    response.headers.update(rate_limit_headers())
    perms = payload.permissions.model_dump(exclude_none=True)
    if not perms.get("readers") and not perms.get("scopes"):
        raise HTTPException(400, detail={"error": {"code": "INVALID_REQUEST", "message": "permissions must include readers or scopes", "details": {}}})
    payload_hash = canonical_json_sha256(payload.model_dump(by_alias=True))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            idem = await conn.fetchrow("SELECT correction_id, payload_hash FROM idempotency WHERE tenant_id=$1 AND key=$2", tenant_id, payload.idempotency_key)
            if idem:
                if idem["payload_hash"] != payload_hash:
                    raise HTTPException(409, detail={"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key used with different payload", "details": {}}})
                existing = await conn.fetchrow("SELECT correction_id, status, supersedes, created_at FROM corrections WHERE correction_id=$1", idem["correction_id"])
                if not existing:
                    raise HTTPException(500, detail={"error": {"code": "INVALID_REQUEST", "message": "Idempotency record points to missing correction", "details": {}}})
                response.status_code = 200
                return CreateCorrectionResponse(correction_id=existing["correction_id"], status=existing["status"], supersedes=existing["supersedes"], created_at=existing["created_at"])
            
            superseded_id = None
            if payload.supersedes is not None:
                target = await conn.fetchrow("SELECT correction_id, subject_type, subject_id, field_key, status FROM corrections WHERE tenant_id=$1 AND correction_id=$2", tenant_id, payload.supersedes)
                if not target:
                    raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": "supersedes target not found", "details": {}}})
                if target["status"] != CorrectionStatus.ACTIVE.value:
                    raise HTTPException(400, detail={"error": {"code": "INVALID_REQUEST", "message": "supersedes target must be ACTIVE", "details": {}}})
                if target["subject_type"] != payload.subject.type or target["subject_id"] != payload.subject.id or target["field_key"] != payload.field_key:
                    raise HTTPException(400, detail={"error": {"code": "INVALID_REQUEST", "message": "supersedes target must match same subject + field_key", "details": {}}})
                superseded_id = target["correction_id"]
            else:
                existing_active = await conn.fetchrow("SELECT correction_id FROM corrections WHERE tenant_id=$1 AND subject_type=$2 AND subject_id=$3 AND field_key=$4 AND status='ACTIVE'", tenant_id, payload.subject.type, payload.subject.id, payload.field_key)
                superseded_id = existing_active["correction_id"] if existing_active else None
            
            new_id = uuid4()
            now = datetime.now(timezone.utc)
            
            # CRITICAL: Supersede old correction BEFORE inserting new one
            if superseded_id:
                await conn.execute("UPDATE corrections SET status='SUPERSEDED' WHERE tenant_id=$1 AND correction_id=$2", tenant_id, superseded_id)
            
            # Now insert new correction
            try:
                await conn.execute("INSERT INTO corrections (correction_id, tenant_id, subject_type, subject_id, field_key, value, class, status, supersedes, permissions, actor_type, actor_id, idempotency_key, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,'ACTIVE',$8,$9,$10,$11,$12,$13)", new_id, tenant_id, payload.subject.type, payload.subject.id, payload.field_key, json.dumps(payload.value), payload.class_.value, superseded_id, json.dumps(perms), payload.actor.type, payload.actor.id, payload.idempotency_key, now)
            except UniqueViolationError:
                raise HTTPException(409, detail={"error": {"code": "INVALID_REQUEST", "message": "ACTIVE invariant violated (concurrent write). Retry.", "details": {}}})
            
            await conn.execute("INSERT INTO idempotency (tenant_id, key, correction_id, payload_hash) VALUES ($1,$2,$3,$4)", tenant_id, payload.idempotency_key, new_id, payload_hash)
            response.status_code = 201
            return CreateCorrectionResponse(correction_id=new_id, status=CorrectionStatus.ACTIVE, supersedes=superseded_id, created_at=now)

@app.get("/v1/facts", response_model=FactsResponse)
async def get_facts(response: Response, subject_type: str = Query(...), subject_id: str = Query(...), requester_id: str = Query(...), requester_scopes: str | None = Query(None), field_keys: str | None = Query(None), q: str | None = Query(None), tenant_id: UUID = Depends(require_tenant)):
    response.headers.update(rate_limit_headers())
    scopes_list = parse_csv(requester_scopes)
    field_keys_list = parse_csv(field_keys)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT correction_id, field_key, value, permissions, created_at, actor_type, actor_id FROM corrections WHERE tenant_id=$1 AND subject_type=$2 AND subject_id=$3 AND status='ACTIVE' AND class='FACT'", tenant_id, subject_type, subject_id)
    permitted = []
    for r in rows:
        permissions = r["permissions"]
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        if is_allowed(requester_id, scopes_list, permissions):
            permitted.append(r)
    if field_keys_list:
        permitted = [r for r in permitted if r["field_key"] in field_keys_list]
    if q:
        q_lower = q.lower()
        permitted = [r for r in permitted if q_lower in r["field_key"].lower() or q_lower in json.dumps(r["value"], ensure_ascii=False).lower()]
    facts = [FactItem(field_key=r["field_key"], value=r["value"], corrected_at=r["created_at"], correction_id=r["correction_id"], actor=Actor(type=r["actor_type"], id=r["actor_id"])) for r in permitted]
    return FactsResponse(subject=Subject(type=subject_type, id=subject_id), facts=facts)

@app.get("/v1/history", response_model=HistoryResponse)
async def get_history(response: Response, subject_type: str = Query(...), subject_id: str = Query(...), requester_id: str = Query(...), requester_scopes: str | None = Query(None), field_key: str | None = Query(None), include_revoked: bool = Query(False), tenant_id: UUID = Depends(require_tenant)):
    response.headers.update(rate_limit_headers())
    scopes_list = parse_csv(requester_scopes)
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = "SELECT correction_id, field_key, value, class, status, supersedes, permissions, created_at, actor_type, actor_id FROM corrections WHERE tenant_id=$1 AND subject_type=$2 AND subject_id=$3"
        params = [tenant_id, subject_type, subject_id]
        if not include_revoked:
            sql += " AND status != 'REVOKED'"
        if field_key:
            params.append(field_key)
            sql += f" AND field_key=${len(params)}"
        sql += " ORDER BY created_at DESC"
        rows = await conn.fetch(sql, *params)
    permitted = []
    for r in rows:
        permissions = r["permissions"]
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        if is_allowed(requester_id, scopes_list, permissions):
            permitted.append(r)
    superseded_by_map = {}
    for r in permitted:
        if r["supersedes"]:
            superseded_by_map[r["supersedes"]] = r["correction_id"]
    history = [HistoryItem(correction_id=r["correction_id"], field_key=r["field_key"], value=r["value"], class_=CorrectionClass(r["class"]), status=CorrectionStatus(r["status"]), supersedes=r["supersedes"], superseded_by=superseded_by_map.get(r["correction_id"]), created_at=r["created_at"], actor=Actor(type=r["actor_type"], id=r["actor_id"])) for r in permitted]
    return HistoryResponse(subject=Subject(type=subject_type, id=subject_id), history=history)
