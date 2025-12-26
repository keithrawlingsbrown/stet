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

class EnforcementEscalation(str, Enum):
    NONE = "NONE"
    WARN = "WARN"
    CRITICAL = "CRITICAL"

class EnforcementHeartbeat(BaseModel):
    system_id: str
    enforced_correction_version: datetime

class EnforcementStatusItem(BaseModel):
    system_id: str
    status: EnforcementDriftStatus
    enforced_correction_version: datetime | None = None
    reported_at: datetime | None = None

class EnforcementStatusResponse(BaseModel):
    evaluated_at: datetime
    heartbeat_interval_seconds: int
    heartbeat_grace_multiplier: float
    systems: list[EnforcementStatusItem]

class EnforcementEscalationSummary(BaseModel):
    total_systems: int
    ok: int
    stale: int
    missing: int

class EnforcementEscalationResponse(BaseModel):
    tenant_id: str
    evaluated_at: datetime
    escalation: EnforcementEscalation
    summary: EnforcementEscalationSummary
    affected_systems: list[EnforcementStatusItem]

def _evaluate_status(
    now: datetime,
    reported_at: datetime,
    threshold_seconds: float,
) -> EnforcementDriftStatus:
    age_seconds = (now - reported_at).total_seconds()
    return EnforcementDriftStatus.OK if age_seconds <= threshold_seconds else EnforcementDriftStatus.STALE

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
                status_value = _evaluate_status(now, row["reported_at"], threshold_seconds)
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
                status_value = _evaluate_status(now, row["reported_at"], threshold_seconds)
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

@router.get("/escalation", response_model=EnforcementEscalationResponse)
async def escalation(
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
            # Check specific system
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
                status_value = _evaluate_status(now, row["reported_at"], threshold_seconds)
                systems = [
                    EnforcementStatusItem(
                        system_id=row["system_id"],
                        status=status_value,
                        enforced_correction_version=row["enforced_correction_version"],
                        reported_at=row["reported_at"],
                    )
                ]
            else:
                # System has never reported - MISSING
                systems = [
                    EnforcementStatusItem(
                        system_id=system_id,
                        status=EnforcementDriftStatus.MISSING,
                        enforced_correction_version=None,
                        reported_at=None,
                    )
                ]
        else:
            # Tenant-wide: all known systems
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
                status_value = _evaluate_status(now, row["reported_at"], threshold_seconds)
                systems.append(
                    EnforcementStatusItem(
                        system_id=row["system_id"],
                        status=status_value,
                        enforced_correction_version=row["enforced_correction_version"],
                        reported_at=row["reported_at"],
                    )
                )

    # Count status types
    counts = {
        EnforcementDriftStatus.OK: 0,
        EnforcementDriftStatus.STALE: 0,
        EnforcementDriftStatus.MISSING: 0,
    }
    for system in systems:
        counts[system.status] += 1

    # Determine escalation level
    if counts[EnforcementDriftStatus.MISSING] > 0:
        escalation_value = EnforcementEscalation.CRITICAL
    elif counts[EnforcementDriftStatus.STALE] > 0:
        escalation_value = EnforcementEscalation.WARN
    else:
        escalation_value = EnforcementEscalation.NONE

    # Only include non-OK systems in affected list
    affected_systems = [system for system in systems if system.status != EnforcementDriftStatus.OK]

    summary = EnforcementEscalationSummary(
        total_systems=len(systems),
        ok=counts[EnforcementDriftStatus.OK],
        stale=counts[EnforcementDriftStatus.STALE],
        missing=counts[EnforcementDriftStatus.MISSING],
    )

    return EnforcementEscalationResponse(
        tenant_id=x_tenant_id,
        evaluated_at=now,
        escalation=escalation_value,
        summary=summary,
        affected_systems=affected_systems,
    )
