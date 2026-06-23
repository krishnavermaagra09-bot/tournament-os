"""
In-process event bus — lightweight, synchronous, non-blocking.
Used ONLY within a single process (bot or web). Cross-process sync
goes through PostgreSQL LISTEN/NOTIFY (see app/services/notify_listener.py).

Usage:
    from app.events.bus import event_bus

    # Subscribe
    @event_bus.subscribe("RegistrationSubmitted")
    async def handle(payload: dict) -> None:
        ...

    # Publish
    await event_bus.publish("RegistrationSubmitted", {"registration_id": "...", ...})
"""
import asyncio
import logging
from collections import defaultdict
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_name: str):
        """Decorator: @event_bus.subscribe('EventName')"""
        def decorator(fn: Handler) -> Handler:
            self._handlers[event_name].append(fn)
            return fn
        return decorator

    def register(self, event_name: str, handler: Handler) -> None:
        self._handlers[event_name].append(handler)

    async def publish(self, event_name: str, payload: dict) -> None:
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return
        results = await asyncio.gather(
            *[h(payload) for h in handlers],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error("Event handler error for %s: %s", event_name, r, exc_info=r)

    def list_events(self) -> list[str]:
        return list(self._handlers.keys())


event_bus = EventBus()
