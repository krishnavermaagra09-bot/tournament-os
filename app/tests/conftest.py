"""
Test configuration and fixtures.
Uses an in-memory SQLite DB via SQLAlchemy async for unit/integration tests.
For tests that require PostgreSQL (JSONB, etc.), set DATABASE_URL to a test PG instance.
"""
import asyncio
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Force test environment
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ADMIN_DASHBOARD_TOKEN", "test_token")
os.environ.setdefault("SECRET_KEY", "test_secret")

from app.database.models.base import Base
import app.database.models  # noqa: F401


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def engine():
    from sqlalchemy.event import listen

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
        autoflush=False, autocommit=False,
    )
    async with factory() as sess:
        async with sess.begin():
            yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def org_and_guild(session: AsyncSession):
    from app.database.models.organization import Organization
    from app.database.models.guild import Guild

    org = Organization(name="Test Org", slug="test-org")
    session.add(org)
    await session.flush()

    guild = Guild(
        organization_id=org.id,
        discord_guild_id="123456789",
        name="Test Server",
    )
    session.add(guild)
    await session.flush()

    return org, guild


@pytest_asyncio.fixture
async def test_user(session: AsyncSession):
    from app.database.repositories.user import UserRepository
    repo = UserRepository(session)
    user, _ = await repo.get_or_create("discord_111", "testuser#0001")
    return user


@pytest_asyncio.fixture
async def draft_tournament(session: AsyncSession, org_and_guild, test_user):
    from app.services.tournament.creation import TournamentCreationService
    from app.database.models.tournament import TournamentFormat

    org, guild = org_and_guild
    svc = TournamentCreationService(session)
    tournament = await svc.create(
        organization_id=org.id,
        guild_id=guild.id,
        created_by=test_user.id,
        name="Test Tournament",
        game="Test Game",
        format=TournamentFormat.SINGLE_ELIMINATION,
    )
    return tournament
