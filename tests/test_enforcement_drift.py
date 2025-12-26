import pytest
import httpx

BASE_URL = "http://localhost:8000"
TENANT_ID = "00000000-0000-0000-0000-000000000001"

@pytest.mark.asyncio
async def test_drift_ok_state():
    """Test 4.1 - OK State: Fresh heartbeat within threshold"""
    async with httpx.AsyncClient() as client:
        heartbeat_response = await client.post(
            f"{BASE_URL}/v1/enforcement/heartbeat",
            json={
                "system_id": "test-ok-system",
                "enforced_correction_version": "2025-01-01T00:00:00Z"
            },
            headers={"X-Tenant-Id": TENANT_ID}
        )
        assert heartbeat_response.status_code == 201
        
        status_response = await client.get(
            f"{BASE_URL}/v1/enforcement/status",
            headers={"X-Tenant-Id": TENANT_ID}
        )
        assert status_response.status_code == 200
        
        data = status_response.json()
        systems = {s["system_id"]: s for s in data["systems"]}
        
        assert "test-ok-system" in systems
        assert systems["test-ok-system"]["status"] == "OK"

@pytest.mark.asyncio
async def test_drift_missing_state():
    """Test 4.3 - MISSING State: System never reported"""
    async with httpx.AsyncClient() as client:
        status_response = await client.get(
            f"{BASE_URL}/v1/enforcement/status?system_id=never-reported-system",
            headers={"X-Tenant-Id": TENANT_ID}
        )
        assert status_response.status_code == 200
        
        data = status_response.json()
        assert len(data["systems"]) == 1
        assert data["systems"][0]["system_id"] == "never-reported-system"
        assert data["systems"][0]["status"] == "MISSING"
