"""
PostgreSQL LISTEN/NOTIFY listener — cross-process event sync.

Usage:
    listener = PGNotifyListener(database_url, handler_fn)
    await listener.start()  # runs forever, reconnects on drop
"""
import asyncio
import json
import logging
import os
import ssl
from typing import Callable, Awaitable

import asyncpg

logger = logging.getLogger(__name__)

CHANNEL = "tournament_os_events"
Handler = Callable[[dict], Awaitable[None]]

# Build an SSL context only when the DATABASE_URL explicitly requests SSL.
# Replit's built-in Postgres (helium) does NOT support SSL — don't enable it there.
_raw_url = os.getenv("DATABASE_URL", "")
_ssl_ctx: ssl.SSLContext | None = None
if "sslmode=require" in _raw_url or "sslmode=verify" in _raw_url:
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE


class PGNotifyListener:
    def __init__(self, database_url: str, handler: Handler):
        # asyncpg uses plain postgresql:// not sqlalchemy's postgresql+asyncpg://
        # Also strip sslmode= param — asyncpg doesn't understand it; we pass ssl= directly.
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        if "sslmode=" in dsn:
            import re
            dsn = re.sub(r"[?&]sslmode=[^&]*", "", dsn).rstrip("?&")
        self._dsn = dsn
        self._handler = handler
        self._conn: asyncpg.Connection | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.warning("LISTEN/NOTIFY disconnected: %s — reconnecting in 5s", e)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._conn:
            await self._conn.close()

    async def _connect_and_listen(self) -> None:
        connect_kwargs: dict = {"dsn": self._dsn}
        if _ssl_ctx is not None:
            connect_kwargs["ssl"] = _ssl_ctx

        self._conn = await asyncpg.connect(**connect_kwargs)
        await self._conn.add_listener(CHANNEL, self._on_notify)
        logger.info("PGNotifyListener: listening on channel '%s'", CHANNEL)
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._conn.fetchval("SELECT 1")
            except Exception:
                break

    async def _on_notify(self, connection, pid, channel, payload) -> None:
        try:
            data = json.loads(payload)
            await self._handler(data)
        except Exception as e:
            logger.error("NOTIFY handler error: %s (payload=%r)", e, payload)
