import os
import asyncpg

_POOL: asyncpg.pool.Pool | None = None

async def get_pool() -> asyncpg.pool.Pool:
    global _POOL
    if _POOL is None:
        _POOL = await asyncpg.create_pool(
            dsn=os.environ.get("DATABASE_URL", "postgresql://stet:stet_dev@postgres:5432/stet"),
            min_size=1,
            max_size=10,
        )
    return _POOL
