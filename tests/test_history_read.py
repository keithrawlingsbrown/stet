import pytest
from uuid import uuid4

@pytest.mark.asyncio
async def test_history_chain(client, tenant_headers):
    base = {
        "subject": {"type": "user", "id": "user_hist"},
        "field_key": "status",
        "class": "FACT",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"}
    }

    await client.post("/v1/corrections", json={**base, "value": "active", "idempotency_key": str(uuid4())}, headers=tenant_headers)
    await client.post("/v1/corrections", json={**base, "value": "cancelled", "idempotency_key": str(uuid4())}, headers=tenant_headers)

    r = await client.get("/v1/history", params={
        "subject_type": "user",
        "subject_id": "user_hist",
        "requester_id": "bot:test"
    }, headers=tenant_headers)

    assert r.status_code == 200
    history = r.json()["history"]
    assert len(history) == 2
    statuses = [h["status"] for h in history]
    assert "ACTIVE" in statuses
    assert "SUPERSEDED" in statuses

@pytest.mark.asyncio
async def test_revoked_handling(client, tenant_headers):
    r1 = await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_gdpr"},
        "field_key": "pii_data",
        "value": "to_be_deleted",
        "class": "FACT",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": str(uuid4())
    }, headers=tenant_headers)

    assert r1.status_code == 201
    correction_id = r1.json()["correction_id"]

    # simulate GDPR revoke with direct DB update
    from app.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE corrections SET status='REVOKED' WHERE correction_id=$1", correction_id)

    r_facts = await client.get("/v1/facts", params={
        "subject_type": "user",
        "subject_id": "user_gdpr",
        "requester_id": "bot:test"
    }, headers=tenant_headers)
    assert r_facts.status_code == 200
    assert r_facts.json()["facts"] == []

    r_hist_default = await client.get("/v1/history", params={
        "subject_type": "user",
        "subject_id": "user_gdpr",
        "requester_id": "bot:test"
    }, headers=tenant_headers)
    assert r_hist_default.status_code == 200
    assert r_hist_default.json()["history"] == []

    r_hist_inc = await client.get("/v1/history", params={
        "subject_type": "user",
        "subject_id": "user_gdpr",
        "requester_id": "bot:test",
        "include_revoked": "true"
    }, headers=tenant_headers)
    assert r_hist_inc.status_code == 200
    history = r_hist_inc.json()["history"]
    assert len(history) == 1
    assert history[0]["status"] == "REVOKED"
