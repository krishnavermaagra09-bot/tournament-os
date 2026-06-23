"""
Duplicate / anti-smurf detection service.

Rules:
- If tournament.allow_duplicates is True: never block, but flag for staff visibility.
- If tournament.allow_duplicates is False: block/flag on any unique field match.
- Built-in checks: Discord ID, team name, captain ID. Custom unique fields also checked.
- Organizer policy always wins — no detection logic overrides it.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.tournament import Tournament
from app.database.models.registration import RegistrationStatus
from app.database.repositories.registration import RegistrationRepository

logger = logging.getLogger(__name__)


class DuplicateDetector:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = RegistrationRepository(session)

    async def check(
        self,
        tournament: Tournament,
        submitted_by_discord_id: str,
        form_data: dict,
        unique_field_keys: list[str],
    ) -> tuple[bool, list[dict]]:
        """
        Returns (is_blocked, duplicate_flags).
        - is_blocked: True only if allow_duplicates is False and a duplicate found.
        - duplicate_flags: list of {field, conflicting_registration_id, value}
        """
        flags: list[dict] = []

        # Check Discord user ID (always a built-in unique check)
        from sqlalchemy import select
        from app.database.models.registration import Registration
        from app.database.models.user import User

        q = (
            select(Registration)
            .join(User, Registration.submitted_by == User.id)
            .where(Registration.organization_id == tournament.organization_id)
            .where(Registration.tournament_id == tournament.id)
            .where(User.discord_user_id == submitted_by_discord_id)
            .where(Registration.deleted_at.is_(None))
            .where(Registration.status != RegistrationStatus.REJECTED)
        )
        result = await self.session.execute(q)
        existing = result.scalars().all()
        for reg in existing:
            flags.append({
                "field": "discord_user_id",
                "value": submitted_by_discord_id,
                "conflicting_registration_id": reg.id,
            })

        # Check organizer-defined unique fields
        for field_key in unique_field_keys:
            value = form_data.get(field_key)
            if not value:
                continue
            conflicting = await self.repo.find_duplicates(
                tournament.organization_id, tournament.id, field_key, str(value)
            )
            for reg in conflicting:
                flags.append({
                    "field": field_key,
                    "value": str(value),
                    "conflicting_registration_id": reg.id,
                })

        is_blocked = bool(flags) and not tournament.allow_duplicates
        if flags:
            level = "BLOCKING" if is_blocked else "flagged (duplicates allowed)"
            logger.info(
                "Duplicate detection: tournament=%s flags=%d %s",
                tournament.id, len(flags), level,
            )

        return is_blocked, flags
