from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, timezone
from enum import Enum
import os
import json
from app.db import get_pool

router = APIRouter(
    prefix="/v1/enforcement",
    tags=["enforcement"]
)

class EnforcementDriftStatus(str, Enum):
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"

class EnforcementHeartbeat(BaseModel):
    system_id: str
    enforced_correction_version: datetime

class EnforcementStatusItem(BaseModel):
    system_id: str
    status: EnforcementDriftStatus  # Changed from str to enum
    enforced_correction_version: datetime | None = None
    reported_at: datetime | None = None

class EnforcementStatusResponse(BaseModel):
    evaluated_at: datetime
    heartbeat_interval_seconds: int
    heartbeat_grace_multiplier: float
    systems: list[EnforcementStatusItem]

@router.post("/heartbeat", status_code=201)
async def heartbeat(
    payload: EnforcementHeartbeat,
    x_tenant_id: str = Header(...),
):
    origin = {
        "service": "stet-api",
        "environment": os.getenv("STET_ENV", "local"),
        "version": os.getenv("STET_VERSION", "dev"),
    }
    if not origin["service"] or not origin["version"]:
        raise HTTPException(
            status_code=400,
            detail="origin attestation required",
        )
    
    query = """
    INSERT INTO enforcement_heartbeats (
        tenant_id,
        system_id,
        enforced_correction_version,
        origin
    ) VALUES ($1, $2, $3, $4);
    """
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            x_tenant_id,
            payload.system_id,
            payload.enforced_correction_version,
            json.dumps(origin),
        )
    
    return {"status": "ok"}

@router.get("/status", response_model=EnforcementStatusResponse)
async def status(
    x_tenant_id: str = Header(...),
    system_id: str | None = Query(None),
):
    heartbeat_interval_seconds = int(os.getenv("STET_HEARTBEAT_INTERVAL_SECONDS", "60"))
    heartbeat_grace_multiplier = float(os.getenv("STET_HEARTBEAT_GRACE_MULTIPLIER", "2"))
    now = datetime.now(timezone.utc)
    threshold_seconds = heartbeat_interval_seconds * heartbeat_grace_multiplier

    pool = await get_pool()
    async with pool.acquire() as conn:
        if system_id:
            row = await conn.fetchrow(
                """
                SELECT system_id, enforced_correction_version, reported_at
                FROM enforcement_heartbeats
                WHERE tenant_id=$1 AND system_id=$2
                ORDER BY reported_at DESC
                LIMIT 1
                """,
                x_tenant_id,
                system_id,
            )
            if row:
                age_seconds = (now - row["reported_at"]).total_seconds()
                status_value = EnforcementDriftStatus.OK if age_seconds <= threshold_seconds else EnforcementDriftStatus.STALE
                systems = [
                    EnforcementStatusItem(
                        system_id=row["system_id"],
                        status=status_value,
                        enforced_correction_version=row["enforced_correction_version"],
                        reported_at=row["reported_at"],
                    )
                ]
            else:
                systems = [
                    EnforcementStatusItem(
                        system_id=system_id,
                        status=EnforcementDriftStatus.MISSING,
                        enforced_correction_version=None,
                        reported_at=None,
                    )
                ]
        else:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (system_id)
                    system_id,
                    enforced_correction_version,
                    reported_at
                FROM enforcement_heartbeats
                WHERE tenant_id=$1
                ORDER BY system_id, reported_at DESC
                """,
                x_tenant_id,
            )
            systems = []
            for row in rows:
                age_seconds = (now - row["reported_at"]).total_seconds()
                status_value = EnforcementDriftStatus.OK if age_seconds <= threshold_seconds else EnforcementDriftStatus.STALE
                systems.append(
                    EnforcementStatusItem(
                        system_id=row["system_id"],
                        status=status_value,
                        enforced_correction_version=row["enforced_correction_version"],
                        reported_at=row["reported_at"],
                    )
                )

    return EnforcementStatusResponse(
        evaluated_at=now,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        heartbeat_grace_multiplier=heartbeat_grace_multiplier,
        systems=systems,
    )
