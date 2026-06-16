import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Module-level dict so unit tests (asyncio.run) can also read captured tokens
_captured_tokens: dict[str, str] = {}


@pytest.fixture(autouse=True)
def mock_email_sending():
    """Replace email functions with no-ops; capture verification tokens for test use."""
    _captured_tokens.clear()

    async def _fake_send_verification(to_email: str, full_name: str, verify_url: str) -> None:
        qs = parse_qs(urlparse(verify_url).query)
        token = qs.get("token", [None])[0]
        if token:
            _captured_tokens[to_email] = token

    async def _fake_send_reset(to_email: str, full_name: str, reset_url: str) -> None:
        pass

    with patch("app.modules.auth.service._send_verification_email", side_effect=_fake_send_verification):
        with patch("app.modules.auth.service._send_reset_email", side_effect=_fake_send_reset):
            yield _captured_tokens


@pytest.fixture
def captured_tokens() -> dict[str, str]:
    """Access the verification tokens captured by mock_email_sending."""
    return _captured_tokens


@pytest.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function")
async def client(db_engine):
    TestSessionLocal = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
