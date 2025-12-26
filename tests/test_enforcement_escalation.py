import pytest
import httpx

BASE_URL = "http://localhost:8000"

@pytest.mark.asyncio
async def test_escalation_none():
    """Test 5.1 - Escalation NONE: All systems OK"""
    tenant_id = "00000000-0000-0000-0000-000000000020"
    
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/v1/enforcement/heartbeat",
            json={
                "system_id": "healthy-system",
                "enforced_correction_version": "2025-01-01T00:00:00Z"
            },
            headers={"X-Tenant-Id": tenant_id}
        )
        
        response = await client.get(
            f"{BASE_URL}/v1/enforcement/escalation",
            headers={"X-Tenant-Id": tenant_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["tenant_id"] == tenant_id
        assert data["escalation"] == "NONE"
        assert data["summary"]["ok"] >= 1
        assert len(data["affected_systems"]) == 0

@pytest.mark.asyncio
async def test_escalation_critical():
    """Test 5.3 - Escalation CRITICAL: System never reported"""
    tenant_id = "00000000-0000-0000-0000-000000000021"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/v1/enforcement/escalation?system_id=critical-missing-system",
            headers={"X-Tenant-Id": tenant_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["escalation"] == "CRITICAL"
        assert data["summary"]["missing"] == 1
        assert len(data["affected_systems"]) == 1
        assert data["affected_systems"][0]["status"] == "MISSING"
