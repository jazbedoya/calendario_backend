#!/bin/sh
set -e

echo "==> Creating/verifying tables via SQLAlchemy..."
python - <<'PYEOF'
import asyncio
import app.modules.auth.models       # noqa: F401
import app.modules.calendar.models   # noqa: F401
import app.modules.events.models     # noqa: F401
import app.modules.context.models    # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine
from app.database import Base
from app.config import settings

async def main():
    engine = create_async_engine(str(settings.database_url))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables OK")

asyncio.run(main())
PYEOF

echo "==> Stamping alembic to head..."
alembic stamp head

echo "==> Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
