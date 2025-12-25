from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from datetime import datetime
import os
import json
from app.db import get_pool

router = APIRouter(
    prefix="/v1/enforcement",
    tags=["enforcement"]
)

class EnforcementHeartbeat(BaseModel):
    system_id: str
    enforced_correction_version: datetime

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
