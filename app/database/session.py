"""
Async SQLAlchemy session factory.

SSL is always enabled with CERT_NONE so Railway/Render/Neon PostgreSQL
connections work regardless of whether the URL includes sslmode=require.
asyncpg does not accept sslmode as a URL query param — we strip it and
pass ssl via connect_args instead.
"""
import os
import ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

_raw_url = os.getenv("DATABASE_URL", "")

# Enable SSL only when the URL explicitly requests it (Railway/Render/Neon).
# Replit's built-in Postgres (helium) does NOT support SSL — enabling it there
# causes "rejected SSL upgrade" errors.
_wants_ssl = (
    "sslmode=require" in _raw_url
    or "sslmode=verify" in _raw_url
)

_connect_args: dict = {}
if _wants_ssl:
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
    connect_args=_connect_args,
    poolclass=NullPool if settings.is_test else None,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db_session() -> AsyncSession:
    """Direct session for non-FastAPI use (bot, background jobs)."""
    return AsyncSessionLocal()


async def get_session() -> AsyncSession:
    """FastAPI dependency — yields an async session and closes it after the request."""
    async with AsyncSessionLocal() as session:
        yield session
