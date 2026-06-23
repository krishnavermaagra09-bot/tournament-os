"""
Auto Form Builder — generates registration fields from tournament settings.

No manual form setup required. The form is derived entirely from:
  - tournament.team_size_type  (SOLO / DUO / TRIO / SQUAD / TEAM / HYBRID)
  - tournament.max_team_size   (exact number of player slots)
  - tournament.game            (used for IGN label wording)

Solo tournaments:   one player fills in their own info.
Team tournaments:   the team captain fills in info for ALL players at once.

Returns a list of page-dicts, each with up to 5 fields (Discord modal limit).
Call get_or_create_auto_form() to persist the form to the DB if none exists.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tournament import Tournament, TeamSizeType

logger = logging.getLogger(__name__)


def build_auto_fields(tournament: Tournament) -> list[list[dict]]:
    """
    Return a list of pages.  Each page is a list[dict] of ≤5 field descriptors
    ready to pass to RegistrationModal or FormBuilderService.create_form().

    Field dict keys:
        field_key, label, field_type, is_required, is_unique,
        placeholder, long_text (bool alias for LONG_TEXT)
    """
    size_type = tournament.team_size_type
    max_size = max(tournament.max_team_size or 1, 1)
    game = tournament.game or "Game"

    # ── SOLO — only the registering player ───────────────────────────────────
    if size_type == TeamSizeType.SOLO or max_size == 1:
        return [[
            {
                "field_key": "in_game_name",
                "label": f"{game} Username / IGN",
                "field_type": "short_text",
                "is_required": True,
                "is_unique": True,
                "placeholder": "Your exact in-game name",
                "long_text": False,
            },
            {
                "field_key": "platform_id",
                "label": "Platform ID (optional)",
                "field_type": "short_text",
                "is_required": False,
                "is_unique": False,
                "placeholder": "e.g. Steam / PSN / Xbox / Battle.net ID",
                "long_text": False,
            },
        ]]

    # ── TEAM — captain registers everyone ────────────────────────────────────
    # Page 1 always has: team_name + up to 4 player IGNs
    # Extra players overflow to page 2 (up to 4 more)
    fields_page1: list[dict] = [
        {
            "field_key": "team_name",
            "label": "Team Name",
            "field_type": "short_text",
            "is_required": True,
            "is_unique": True,
            "placeholder": "Your team's official name",
            "long_text": False,
        },
    ]

    all_player_fields: list[dict] = []
    for i in range(1, max_size + 1):
        suffix = " (You — Captain)" if i == 1 else f""
        all_player_fields.append({
            "field_key": f"player_{i}_ign",
            "label": f"Player {i} IGN{suffix}"[:45],
            "field_type": "short_text",
            "is_required": True,
            "is_unique": False,
            "placeholder": f"Player {i}'s exact in-game name",
            "long_text": False,
        })

    # Page 1: team_name + first 4 players (5 fields total)
    fields_page1.extend(all_player_fields[:4])
    pages = [fields_page1]

    # Page 2: players 5-9 (if any), up to 5 per page
    remaining = all_player_fields[4:]
    while remaining:
        pages.append(remaining[:5])
        remaining = remaining[5:]

    return pages


async def get_or_create_auto_form(
    session: AsyncSession,
    tournament: Tournament,
) -> None:
    """
    Idempotent: creates a RegistrationForm for the tournament if none exists.
    Safe to call every time registration opens.
    """
    from app.services.registration.form_builder import FormBuilderService

    fb = FormBuilderService(session)
    existing = await fb.get_active_form(tournament.organization_id, tournament.id)
    if existing:
        logger.debug(
            "Auto-form: existing form found for tournament %s (v%s), skipping",
            tournament.id[:8], existing.version,
        )
        return

    pages = build_auto_fields(tournament)
    # Flatten all pages into one form — FormBuilderService handles the fields
    all_fields = [f for page in pages for f in page]

    await fb.create_form(tournament.organization_id, tournament.id, all_fields)
    logger.info(
        "Auto-form: created form with %d fields for tournament %s (%s)",
        len(all_fields), tournament.id[:8], tournament.team_size_type.value,
    )


def fields_to_modal_pages(tournament: Tournament) -> list[list[dict]]:
    """
    Return modal-ready pages (list of ≤5 field dicts with 'long_text' bool).
    Call this when building RegistrationModal directly without persisting to DB.
    """
    return build_auto_fields(tournament)
