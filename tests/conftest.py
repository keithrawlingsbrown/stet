import pytest
from uuid import uuid4
from httpx import AsyncClient

# Test tenant for all tests
TEST_TENANT_ID = str(uuid4())

@pytest.fixture
async def client():
    """HTTP client for testing live API server"""
    async with AsyncClient(base_url="http://api:8000", timeout=30.0) as ac:
        yield ac

@pytest.fixture
def tenant_headers():
    """Headers with tenant ID"""
    return {"X-Tenant-Id": TEST_TENANT_ID}
