import pytest
from uuid import uuid4

@pytest.mark.asyncio
async def test_create_correction_basic(client, tenant_headers):
    payload = {
        "subject": {"type": "user", "id": "user_123"},
        "field_key": "medical.allergy",
        "value": "peanuts",
        "class": "FACT",
        "permissions": {"readers": ["bot:support_v2"]},
        "actor": {"type": "user", "id": "user_123"},
        "idempotency_key": str(uuid4())
    }

    r = await client.post("/v1/corrections", json=payload, headers=tenant_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ACTIVE"
    assert body["supersedes"] is None
    assert "correction_id" in body

@pytest.mark.asyncio
async def test_automatic_superseding(client, tenant_headers):
    base = {
        "subject": {"type": "user", "id": "user_456"},
        "field_key": "subscription.status",
        "permissions": {"readers": ["bot:support_v2"]},
        "actor": {"type": "system", "id": "crm"},
        "class": "FACT"
    }

    r1 = await client.post("/v1/corrections", json={**base, "value": "active", "idempotency_key": str(uuid4())}, headers=tenant_headers)
    assert r1.status_code == 201
    v1_id = r1.json()["correction_id"]

    r2 = await client.post("/v1/corrections", json={**base, "value": "cancelled", "idempotency_key": str(uuid4())}, headers=tenant_headers)
    assert r2.status_code == 201
    assert r2.json()["supersedes"] == v1_id

@pytest.mark.asyncio
async def test_idempotency_retry(client, tenant_headers):
    key = str(uuid4())
    payload = {
        "subject": {"type": "user", "id": "user_789"},
        "field_key": "consent.do_not_contact",
        "value": True,
        "class": "FACT",
        "permissions": {"readers": ["bot:support_v2"]},
        "actor": {"type": "system", "id": "crm"},
        "idempotency_key": key
    }

    r1 = await client.post("/v1/corrections", json=payload, headers=tenant_headers)
    assert r1.status_code == 201

    r2 = await client.post("/v1/corrections", json=payload, headers=tenant_headers)
    assert r2.status_code == 200
    assert r1.json()["correction_id"] == r2.json()["correction_id"]

@pytest.mark.asyncio
async def test_idempotency_conflict(client, tenant_headers):
    key = str(uuid4())

    r1 = await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_conflict"},
        "field_key": "test_field",
        "value": "A",
        "class": "FACT",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": key
    }, headers=tenant_headers)
    assert r1.status_code == 201

    r2 = await client.post("/v1/corrections", json={
        "subject": {"type": "user", "id": "user_conflict"},
        "field_key": "test_field",
        "value": "B",
        "class": "FACT",
        "permissions": {"readers": ["bot:test"]},
        "actor": {"type": "system", "id": "test"},
        "idempotency_key": key
    }, headers=tenant_headers)

    assert r2.status_code == 409
