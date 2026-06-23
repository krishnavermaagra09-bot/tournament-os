"""
Registration approval service — handles the full approval/rejection/waitlist flow.
When a registration is manually approved, a Team record is created automatically
and (if enabled) a private team hub is provisioned on Discord.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.registration import Registration, RegistrationStatus
from app.database.models.team import Team, TeamMember
from app.database.models.tournament import Tournament
from app.database.repositories.audit import AuditRepository
from app.database.repositories.registration import RegistrationRepository
from app.database.repositories.team import TeamRepository
from app.database.repositories.user import UserRepository
from app.events.publishers import registration as reg_pub
from app.services.registration.duplicate_detector import DuplicateDetector

logger = logging.getLogger(__name__)


class RegistrationApprovalService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = RegistrationRepository(session)
        self.audit = AuditRepository(session)
        self.team_repo = TeamRepository(session)
        self.user_repo = UserRepository(session)
        self.detector = DuplicateDetector(session)

    async def submit(
        self,
        tournament: Tournament,
        discord_user_id: str,
        form_data: dict,
        unique_field_keys: list[str] | None = None,
    ) -> Registration:
        """Submit a registration, run duplicate detection, auto-approve if no issues."""
        user, _ = await self.user_repo.get_or_create(discord_user_id, form_data.get("username", "Unknown"))

        unique_fields = unique_field_keys or []
        is_blocked, flags = await self.detector.check(
            tournament, discord_user_id, form_data, unique_fields
        )

        if is_blocked:
            raise ValueError("Registration blocked: duplicate detected and duplicates are not allowed.")

        initial_status = RegistrationStatus.PENDING
        if flags:
            initial_status = RegistrationStatus.FLAGGED
        elif not unique_fields:
            initial_status = RegistrationStatus.AUTO_APPROVED

        reg = Registration(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            submitted_by=user.id,
            form_data=form_data,
            duplicate_flags=flags,
            status=initial_status,
        )
        self.session.add(reg)
        await self.session.flush()
        await self.session.refresh(reg)

        # Auto-create team for solo players when flag is enabled OR auto-approved
        solo_auto_team: bool = (tournament.feature_flags or {}).get("solo_auto_team", False)
        should_create_team = (
            initial_status == RegistrationStatus.AUTO_APPROVED
            or (solo_auto_team and initial_status in (RegistrationStatus.PENDING, RegistrationStatus.AUTO_APPROVED))
        )
        if should_create_team:
            await self._create_team_for_registration(tournament, reg, user.id, form_data)
            if initial_status == RegistrationStatus.PENDING and solo_auto_team:
                logger.info(
                    "solo_auto_team: created team immediately for pending reg %s in tournament %s",
                    reg.id[:8], tournament.id[:8],
                )

        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.submitted",
            actor_id=user.id,
            target_type="registration",
            target_id=reg.id,
            payload={"status": initial_status.value, "flags": len(flags)},
        )

        await reg_pub.registration_submitted(
            reg.id, tournament.id, tournament.organization_id,
            user.id, has_duplicates=bool(flags)
        )
        return reg

    async def approve(
        self,
        registration_id: str,
        tournament: Tournament,
        reviewer_id: str,
        notes: str | None = None,
        bot=None,
    ) -> Registration:
        reg = await self.repo.update_status(
            registration_id,
            tournament.organization_id,
            tournament.id,
            RegistrationStatus.MANUALLY_APPROVED,
            reviewed_by=reviewer_id,
        )
        if not reg:
            raise ValueError(f"Registration {registration_id} not found")

        if notes:
            reg.notes = notes
            await self.session.flush()

        submitter = await self.user_repo.get_by_id(reg.submitted_by)
        team: Team | None = None
        if submitter:
            existing_team = await self.team_repo.get_by_captain(
                tournament.organization_id, tournament.id, submitter.discord_user_id
            )
            if not existing_team:
                team = await self._create_team_for_registration(
                    tournament, reg, submitter.id, reg.form_data
                )
            else:
                team = existing_team

        # 2.0: Provision private team hub if enabled and bot is available
        if team and bot and (tournament.team_hub_config or {}).get("enabled"):
            try:
                from app.services.team_hub import TeamHubService
                hub_svc = TeamHubService(self.session)
                await hub_svc.provision(
                    bot=bot,
                    tournament=tournament,
                    team=team,
                    hub_config=tournament.team_hub_config,
                )
            except Exception as exc:
                logger.warning("Team hub provisioning failed for team %s: %s", team.id, exc)

        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.approved",
            actor_id=reviewer_id,
            target_type="registration",
            target_id=registration_id,
            payload={},
        )

        await reg_pub.registration_approved(
            registration_id, tournament.id, tournament.organization_id,
            reg.submitted_by, reviewer_id,
        )
        return reg

    async def reject(
        self,
        registration_id: str,
        tournament: Tournament,
        reviewer_id: str,
        reason: str,
    ) -> Registration:
        reg = await self.repo.update_status(
            registration_id,
            tournament.organization_id,
            tournament.id,
            RegistrationStatus.REJECTED,
            reviewed_by=reviewer_id,
            rejection_reason=reason,
        )
        if not reg:
            raise ValueError(f"Registration {registration_id} not found")

        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.rejected",
            actor_id=reviewer_id,
            target_type="registration",
            target_id=registration_id,
            payload={"reason": reason},
        )

        await reg_pub.registration_rejected(
            registration_id, tournament.id, tournament.organization_id,
            reg.submitted_by, reviewer_id, reason,
        )
        return reg

    async def flag(
        self,
        registration_id: str,
        tournament: Tournament,
        actor_id: str,
        notes: str | None = None,
    ) -> Registration:
        reg = await self.repo.update_status(
            registration_id, tournament.organization_id, tournament.id,
            RegistrationStatus.FLAGGED, reviewed_by=actor_id,
        )
        if not reg:
            raise ValueError(f"Registration {registration_id} not found")
        if notes:
            reg.notes = notes
            await self.session.flush()
        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.flagged",
            actor_id=actor_id,
            target_type="registration",
            target_id=registration_id,
            payload={"notes": notes},
        )
        return reg

    async def waitlist(
        self,
        registration_id: str,
        tournament: Tournament,
        actor_id: str,
        notes: str | None = None,
    ) -> Registration:
        """Move registration to waitlist — team slot reserved but not confirmed."""
        reg = await self.repo.update_status(
            registration_id, tournament.organization_id, tournament.id,
            RegistrationStatus.WAITLISTED, reviewed_by=actor_id,
        )
        if not reg:
            raise ValueError(f"Registration {registration_id} not found")
        if notes:
            reg.notes = notes
            await self.session.flush()
        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.waitlisted",
            actor_id=actor_id,
            target_type="registration",
            target_id=registration_id,
            payload={"notes": notes},
        )
        return reg

    async def checkin(
        self,
        registration_id: str,
        tournament: Tournament,
        actor_id: str,
    ) -> Registration:
        """Mark registration as checked-in."""
        reg = await self.repo.update_status(
            registration_id, tournament.organization_id, tournament.id,
            RegistrationStatus.CHECKED_IN, reviewed_by=actor_id,
        )
        if not reg:
            raise ValueError(f"Registration {registration_id} not found")
        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="registration.checked_in",
            actor_id=actor_id,
            target_type="registration",
            target_id=registration_id,
            payload={},
        )
        return reg

    async def _create_team_for_registration(
        self,
        tournament: Tournament,
        reg: Registration,
        captain_user_id: str,
        form_data: dict,
    ) -> Team:
        team_name = (
            form_data.get("team_name")
            or form_data.get("in_game_name")
            or form_data.get("username")
            or "Unknown Team"
        )
        team_name = str(team_name)[:100]

        team = Team(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            name=team_name,
            captain_id=captain_user_id,
            checkin_status="not_checked_in",
            is_reserve=False,
            team_data=form_data,
        )
        self.session.add(team)
        await self.session.flush()
        await self.session.refresh(team)

        reg.team_id = team.id
        await self.session.flush()

        from datetime import datetime, timezone
        member = TeamMember(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            team_id=team.id,
            user_id=captain_user_id,
            role="captain",
            is_active=True,
            joined_at=datetime.now(timezone.utc),
        )
        self.session.add(member)
        await self.session.flush()

        await self.audit.log(
            organization_id=tournament.organization_id,
            tournament_id=tournament.id,
            action="team.created_from_registration",
            actor_id=captain_user_id,
            target_type="team",
            target_id=team.id,
            payload={"registration_id": reg.id, "team_name": team_name},
        )

        logger.info("Team %s created for registration %s", team.id, reg.id)
        return team
