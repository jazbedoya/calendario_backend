#!/bin/sh
set -e

echo "==> Creating/verifying tables via SQLAlchemy..."
python - <<'PYEOF'
import asyncio
import app.modules.auth.models       # noqa: F401
import app.modules.calendar.models   # noqa: F401
import app.modules.events.models     # noqa: F401
import app.modules.context.models    # noqa: F401
import app.modules.tasks.models      # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import Base
from app.config import settings

raw = str(settings.database_url)
async_url = (
    raw
    .replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    .replace("postgresql://", "postgresql+asyncpg://", 1)
    .replace("postgres://", "postgresql+asyncpg://", 1)
)

async def main():
    engine = create_async_engine(async_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables OK")

asyncio.run(main())
PYEOF

echo "==> Running alembic migrations..."
alembic upgrade head || { echo "Migration failed, stamping head..."; alembic stamp head; }

echo "==> Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
