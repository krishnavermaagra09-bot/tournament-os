"""
Webhook delivery service.

Webhooks are stored per-tournament in channel_config.webhooks:
  [{"url": "https://...", "secret": "optional-hmac-secret", "events": ["*"]}]

On any event bus event, the service looks up active tournaments and fires
HTTP POST requests to all registered webhooks. Each delivery is:
  - Signed with HMAC-SHA256 (X-Signature-256 header) if a secret is set.
  - Fire-and-forget with a short timeout so webhook failures never block events.

Payload shape:
  {
    "event": "TournamentStatusChanged",
    "tournament_id": "...",
    "organization_id": "...",
    "timestamp": "2026-06-22T00:00:00Z",
    "data": { ...original event payload... }
  }
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds per webhook delivery


async def deliver(
    event_name: str,
    tournament_id: str,
    organization_id: str,
    payload: dict,
) -> None:
    """Deliver an event to all registered webhooks for the given tournament."""
    try:
        await _deliver_inner(event_name, tournament_id, organization_id, payload)
    except Exception as exc:
        logger.warning("Webhook delivery outer error: %s", exc)


async def _deliver_inner(
    event_name: str,
    tournament_id: str,
    organization_id: str,
    payload: dict,
) -> None:
    if not tournament_id or not organization_id:
        return

    # Load webhook config from tournament
    from app.database.session import AsyncSessionLocal
    from app.database.models.tournament import Tournament

    async with AsyncSessionLocal() as session:
        t = await session.get(Tournament, tournament_id)
        if not t:
            return
        webhooks: list[dict] = t.channel_config.get("webhooks", [])

    if not webhooks:
        return

    body = json.dumps(
        {
            "event": event_name,
            "tournament_id": tournament_id,
            "organization_id": organization_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "data": payload,
        },
        default=str,
    ).encode()

    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not installed — webhook delivery skipped")
        return

    async with aiohttp.ClientSession() as http:
        for wh in webhooks:
            url = wh.get("url", "")
            if not url:
                continue

            # Event filter — ["*"] means all events
            allowed = wh.get("events", ["*"])
            if "*" not in allowed and event_name not in allowed:
                continue

            headers = {
                "Content-Type": "application/json",
                "X-Tournament-OS-Event": event_name,
            }

            secret = wh.get("secret", "")
            if secret:
                sig = hmac.new(
                    secret.encode(), body, hashlib.sha256
                ).hexdigest()
                headers["X-Signature-256"] = f"sha256={sig}"

            try:
                async with http.post(
                    url,
                    data=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            "Webhook %s returned HTTP %d for event %s",
                            url[:60], resp.status, event_name,
                        )
                    else:
                        logger.debug(
                            "Webhook delivered: %s event=%s status=%d",
                            url[:60], event_name, resp.status,
                        )
            except Exception as exc:
                logger.warning(
                    "Webhook delivery failed for %s: %s", url[:60], exc
                )


def register_webhook_subscriber() -> None:
    """Wire the webhook service into the event bus for all event types."""
    from app.events.bus import event_bus

    @event_bus.subscribe("TournamentStatusChanged")
    async def _wh_status(payload: dict) -> None:
        await deliver("TournamentStatusChanged", payload.get("tournament_id", ""), payload.get("organization_id", ""), payload)

    @event_bus.subscribe("MatchCompleted")
    async def _wh_match_done(payload: dict) -> None:
        await deliver("MatchCompleted", payload.get("tournament_id", ""), payload.get("organization_id", ""), payload)

    @event_bus.subscribe("RegistrationApproved")
    async def _wh_reg_approved(payload: dict) -> None:
        await deliver("RegistrationApproved", payload.get("tournament_id", ""), payload.get("organization_id", ""), payload)

    @event_bus.subscribe("DisputeOpened")
    async def _wh_dispute(payload: dict) -> None:
        await deliver("DisputeOpened", payload.get("tournament_id", ""), payload.get("organization_id", ""), payload)
