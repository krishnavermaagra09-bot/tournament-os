"""
Match score submission and override service.
All multi-step operations are wrapped in a transaction at the caller level.

Two submission flows:
  1. Staff/referee submits final result directly → submit_score()
  2. Each team captain submits their result independently → submit_team_score_claim()
     • Both agree   → auto-approved, match completed immediately
     • Both disagree → auto-dispute created, match set to PROTESTED

After a winner is recorded, BracketAdvancement slots the winner into the next match.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.match import Match, MatchStatus, BattleRoyaleResult
from app.database.repositories.audit import AuditRepository
from app.database.repositories.match import MatchRepository
from app.events.publishers import match as match_pub
from app.services.standings.calculator import StandingsCalculator

logger = logging.getLogger(__name__)


class ScoreHandler:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MatchRepository(session)
        self.audit = AuditRepository(session)
        self.standings = StandingsCalculator(session)

    async def submit_score(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        submitted_by: str,
        score_team1: dict,
        score_team2: dict,
        winner_id: str | None = None,
        loser_id: str | None = None,
        is_override: bool = False,
        override_reason: str | None = None,
    ) -> Match:
        match = await self.repo.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")
        match_id = match.id  # normalize short ID to full UUID
        tournament_id = match.tournament_id

        if match.status == MatchStatus.COMPLETED and not is_override:
            raise ValueError("Match already completed. Use score override to change the result.")

        updated = await self.repo.submit_score(
            match_id, organization_id, tournament_id,
            score_team1=score_team1,
            score_team2=score_team2,
            winner_id=winner_id,
            loser_id=loser_id,
            override_by=submitted_by if is_override else None,
            override_reason=override_reason,
        )

        action = "match.score_overridden" if is_override else "match.score_submitted"
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action=action,
            actor_id=submitted_by,
            target_type="match",
            target_id=match_id,
            payload={
                "score_team1": score_team1,
                "score_team2": score_team2,
                "winner_id": winner_id,
                "override_reason": override_reason,
            },
        )

        await match_pub.score_submitted(
            match_id, tournament_id, organization_id,
            submitted_by, score_team1, score_team2,
        )

        if winner_id:
            await match_pub.match_completed(
                match_id, tournament_id, organization_id, winner_id, loser_id
            )

            # Update standings for all formats
            await self.standings.update_after_match(
                organization_id, tournament_id, match_id,
                winner_id=winner_id, loser_id=loser_id,
            )

            # Advance winner to next match in elimination brackets
            await self._advance_bracket(updated, organization_id, tournament_id)

        return updated

    async def submit_team_score_claim(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        claiming_team_id: str,
        submitted_by_discord_id: str,
        winner_team_id: str,
        score: dict | None = None,
    ) -> str:
        """
        Record a team captain's score claim. Called once per team.

        Returns one of:
          "pending"       — waiting for the other team to submit
          "auto_approved" — both teams agreed; match auto-completed
          "disputed"      — teams disagreed; auto-dispute opened, match → PROTESTED
        """
        match = await self.repo.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")

        full_match_id = match.id
        tournament_id = match.tournament_id

        if match.status == MatchStatus.COMPLETED:
            raise ValueError("Match is already completed.")

        if claiming_team_id not in (match.team1_id, match.team2_id):
            raise ValueError("Your team is not a participant in this match.")

        # Store claim in settings JSONB
        settings: dict = dict(match.settings or {})
        pending: dict = dict(settings.get("pending_score_claims", {}))

        pending[claiming_team_id] = {
            "winner_id": winner_team_id,
            "score": score or {},
            "submitted_by": submitted_by_discord_id,
        }
        settings["pending_score_claims"] = pending
        match.settings = settings
        await self.session.flush()

        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="match.team_score_claim",
            actor_id=submitted_by_discord_id,
            target_type="match",
            target_id=full_match_id,
            payload={"team_id": claiming_team_id, "claimed_winner": winner_team_id},
        )

        # Check if both teams have submitted
        team1_claim = pending.get(match.team1_id) if match.team1_id else None
        team2_claim = pending.get(match.team2_id) if match.team2_id else None

        if not team1_claim or not team2_claim:
            logger.info(
                "Match %s: score claim from team %s recorded — awaiting other team",
                full_match_id[:8], claiming_team_id[:8],
            )
            return "pending"

        # Both teams submitted — resolve
        agreed = team1_claim["winner_id"] == team2_claim["winner_id"]

        # Clear pending claims
        settings.pop("pending_score_claims", None)
        match.settings = settings
        await self.session.flush()

        if agreed:
            winner_id = team1_claim["winner_id"]
            loser_id = (
                match.team2_id if winner_id == match.team1_id
                else match.team1_id
            )

            # Use the winner's team's submitted score as authoritative
            if winner_id == match.team1_id:
                score_team1 = team1_claim.get("score") or {}
                score_team2 = team2_claim.get("score") or {}
            else:
                score_team1 = team2_claim.get("score") or {}
                score_team2 = team1_claim.get("score") or {}

            logger.info(
                "Match %s: both teams agree — winner=%s, auto-approving",
                full_match_id[:8], winner_id[:8] if winner_id else "None",
            )
            await self.submit_score(
                match_id=full_match_id,
                tournament_id=tournament_id,
                organization_id=organization_id,
                submitted_by="auto_approval:score_agreement",
                score_team1=score_team1,
                score_team2=score_team2,
                winner_id=winner_id,
                loser_id=loser_id,
            )
            return "auto_approved"
        else:
            # Scores disagree — create auto-dispute and flag the match
            logger.info(
                "Match %s: teams disagree on winner — opening auto-dispute",
                full_match_id[:8],
            )
            match.status = MatchStatus.PROTESTED
            await self.session.flush()

            await self.audit.log(
                organization_id=organization_id,
                tournament_id=tournament_id,
                action="match.score_dispute_auto_opened",
                actor_id="system",
                target_type="match",
                target_id=full_match_id,
                payload={
                    "team1_claim": team1_claim,
                    "team2_claim": team2_claim,
                },
            )

            # Publish dispute event so notification handler alerts staff.
            # (Full Dispute row requires a real user FK, so we fire the event
            # directly instead of calling DisputeCaseManager.open_dispute.)
            try:
                await match_pub.dispute_opened(
                    dispute_id=f"auto-{full_match_id[:8]}",
                    match_id=full_match_id,
                    tournament_id=tournament_id,
                    organization_id=organization_id,
                    opened_by="system",
                    case_type="wrong_score",
                )
            except Exception as exc:
                logger.warning("Failed to publish auto-dispute event for match %s: %s", full_match_id[:8], exc)

            return "disputed"

    async def _advance_bracket(
        self,
        completed_match: Match,
        organization_id: str,
        tournament_id: str,
    ) -> None:
        """
        Advance the winner to the next bracket slot for elimination formats.
        Skipped gracefully for round-robin / swiss (no fixed next-match slot).
        """
        if not completed_match.bracket_id:
            return

        try:
            from app.database.repositories.tournament import TournamentRepository
            from app.database.models.tournament import TournamentFormat
            from app.services.bracket.advancement import BracketAdvancement

            t_repo = TournamentRepository(self.session)
            tournament = await t_repo.get_by_id(tournament_id, organization_id)
            if not tournament:
                return

            elimination_formats = {
                TournamentFormat.SINGLE_ELIMINATION,
                TournamentFormat.DOUBLE_ELIMINATION,
                TournamentFormat.TRIPLE_ELIMINATION,
            }
            if tournament.format not in elimination_formats:
                return

            advancement = BracketAdvancement(self.session)
            await advancement.advance_winner(
                completed_match=completed_match,
                organization_id=organization_id,
                tournament_id=tournament_id,
            )
        except Exception as e:
            logger.error(
                "Bracket advancement failed for match %s: %s", completed_match.id, e, exc_info=True
            )
            try:
                await self.audit.log(
                    organization_id=organization_id,
                    tournament_id=tournament_id,
                    action="match.bracket_advancement_failed",
                    actor_id="system",
                    target_type="match",
                    target_id=completed_match.id,
                    payload={"error": str(e)},
                )
            except Exception:
                pass

    async def submit_battle_royale(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        submitted_by: str,
        results: list[dict],
    ) -> list[BattleRoyaleResult]:
        """
        results: [{team_id, lobby_number, placement, kill_points, placement_points,
                   bonus_points, penalty_points, notes}]
        """
        match = await self.repo.get_by_id(match_id, organization_id, tournament_id)
        if not match:
            raise ValueError(f"Match {match_id} not found")
        match_id = match.id
        tournament_id = match.tournament_id

        saved: list[BattleRoyaleResult] = []
        for r in results:
            br = BattleRoyaleResult(
                organization_id=organization_id,
                tournament_id=tournament_id,
                match_id=match_id,
                team_id=r["team_id"],
                lobby_number=r["lobby_number"],
                placement=r.get("placement"),
                kill_points=r.get("kill_points", 0),
                placement_points=r.get("placement_points", 0),
                bonus_points=r.get("bonus_points", 0),
                penalty_points=r.get("penalty_points", 0),
                notes=r.get("notes", {}),
            )
            saved.append(await self.repo.save_br_result(br))

        await self.repo.update_status(match_id, organization_id, tournament_id, MatchStatus.COMPLETED)
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action="match.br_results_submitted",
            actor_id=submitted_by,
            target_type="match",
            target_id=match_id,
            payload={"result_count": len(saved)},
        )
        await self.standings.update_br_standings(organization_id, tournament_id)
        return saved

    async def set_status(
        self,
        match_id: str,
        tournament_id: str,
        organization_id: str,
        status: MatchStatus,
        actor_id: str,
    ) -> Match:
        updated = await self.repo.update_status(match_id, organization_id, tournament_id, status)
        if not updated:
            raise ValueError(f"Match {match_id} not found")
        await self.audit.log(
            organization_id=organization_id,
            tournament_id=tournament_id,
            action=f"match.status_{status.value}",
            actor_id=actor_id,
            target_type="match",
            target_id=match_id,
            payload={"new_status": status.value},
        )
        if status == MatchStatus.LIVE:
            await match_pub.match_started(match_id, tournament_id, organization_id)
        return updated
