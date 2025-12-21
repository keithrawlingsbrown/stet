import pytest
from uuid import uuid4

@pytest.mark.asyncio
async def test_permission_first(client, tenant_headers):
    await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_perm"},
        "field_key": "sensitive_data",
        "value": "secret",
        "class": "FACT",
        "permissions": {"readers": ["bot:allowed"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": str(uuid4())
    }, headers=tenant_headers)

    r_denied = await client.get("/v1/facts", params={
        "subject_type": "user",
        "subject_id": "user_perm",
        "requester_id": "bot:denied"
    }, headers=tenant_headers)

    assert r_denied.status_code == 200
    assert r_denied.json()["facts"] == []

    r_allowed = await client.get("/v1/facts", params={
        "subject_type": "user",
        "subject_id": "user_perm",
        "requester_id": "bot:allowed"
    }, headers=tenant_headers)

    assert r_allowed.status_code == 200
    facts = r_allowed.json()["facts"]
    assert len(facts) == 1
    assert facts[0]["field_key"] == "sensitive_data"

@pytest.mark.asyncio
async def test_fact_only(client, tenant_headers):
    await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_discard"},
        "field_key": "temp_note",
        "value": "temporary",
        "class": "DISCARDABLE",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": str(uuid4())
    }, headers=tenant_headers)

    r = await client.get("/v1/facts", params={
        "subject_type": "user",
        "subject_id": "user_discard",
        "requester_id": "bot:test"
    }, headers=tenant_headers)

    assert r.status_code == 200
    assert r.json()["facts"] == []

@pytest.mark.asyncio
async def test_cross_subject_isolation(client, tenant_headers):
    await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_a"},
        "field_key": "private_data",
        "value": "user_a_secret",
        "class": "FACT",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": str(uuid4())
    }, headers=tenant_headers)

    r = await client.get("/v1/facts", params={
        "subject_type": "user",
        "subject_id": "user_b",
        "requester_id": "bot:test"
    }, headers=tenant_headers)

    assert r.status_code == 200
    assert r.json()["facts"] == []
