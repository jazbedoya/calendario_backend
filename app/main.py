import asyncio
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

# asyncpg requires SelectorEventLoop on Windows (ProactorEventLoop causes hangs)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import AppException, app_exception_handler, unhandled_exception_handler
from app.modules.auth.router import router as auth_router
from app.modules.calendar.router import router as calendar_router
from app.modules.events.router import router as events_router
from app.modules.context.router import router as context_router
from app.modules.stats.router import router as stats_router
from app.modules.tasks.router import router as tasks_router
from app.modules.home.router import router as home_router

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("startup", env=settings.app_env)
    yield
    log.info("shutdown")


app = FastAPI(
    title="Calendario API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Mobile app (Expo) sends requests from variable origins
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth_router)
app.include_router(calendar_router)
app.include_router(events_router)
app.include_router(context_router)
app.include_router(stats_router)
app.include_router(tasks_router)
app.include_router(home_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
