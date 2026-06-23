"""
Snapshot service — captures full tournament state as an immutable JSON record.

Typical usage (called automatically by event subscribers):
    svc = SnapshotService(session)
    await svc.take(org_id, tournament_id, trigger="bracket_generated")

Snapshots include: tournament metadata, all teams + members, standings,
all matches + scores.  They are read-only records — never modified after
creation.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models.snapshot import TournamentSnapshot

logger = logging.getLogger(__name__)


class SnapshotService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def take(
        self,
        organization_id: str,
        tournament_id: str,
        trigger: str,
        label: str | None = None,
    ) -> TournamentSnapshot:
        """Capture current tournament state and persist a snapshot."""
        state = await self._build_state(organization_id, tournament_id)

        snap = TournamentSnapshot(
            organization_id=organization_id,
            tournament_id=tournament_id,
            trigger=trigger,
            label=label,
            state=state,
        )
        self.session.add(snap)
        await self.session.flush()
        await self.session.refresh(snap)

        logger.info(
            "snapshot taken: trigger=%s tournament=%s snap=%s",
            trigger, tournament_id[:8], snap.id[:8],
        )
        return snap

    async def list_snapshots(
        self, organization_id: str, tournament_id: str, limit: int = 20
    ) -> list[TournamentSnapshot]:
        q = (
            select(TournamentSnapshot)
            .where(
                TournamentSnapshot.organization_id == organization_id,
                TournamentSnapshot.tournament_id == tournament_id,
            )
            .order_by(TournamentSnapshot.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_snapshot(self, snapshot_id: str) -> TournamentSnapshot | None:
        return await self.session.get(TournamentSnapshot, snapshot_id)

    # ── State builder ──────────────────────────────────────────────────────────

    async def _build_state(
        self, organization_id: str, tournament_id: str
    ) -> dict:
        from app.database.models.tournament import Tournament
        from app.database.models.team import Team, TeamMember
        from app.database.models.match import Match
        from app.database.models.standings import Standings

        state: dict = {}

        # Tournament metadata
        t = await self.session.get(Tournament, tournament_id)
        if t:
            state["tournament"] = {
                "id": t.id,
                "name": t.name,
                "format": t.format.value if t.format else None,
                "status": t.status.value if t.status else None,
                "game": t.game,
                "region": t.region,
            }

        # Teams
        teams_q = (
            select(Team)
            .where(
                Team.organization_id == organization_id,
                Team.tournament_id == tournament_id,
                Team.deleted_at.is_(None),
            )
        )
        teams = list((await self.session.execute(teams_q)).scalars().all())
        state["teams"] = [
            {
                "id": team.id,
                "name": team.name,
                "seed": team.seed,
                "checkin_status": team.checkin_status,
                "is_reserve": team.is_reserve,
            }
            for team in teams
        ]

        # Matches
        matches_q = (
            select(Match)
            .where(
                Match.organization_id == organization_id,
                Match.tournament_id == tournament_id,
                Match.deleted_at.is_(None),
            )
            .order_by(Match.round)
        )
        matches = list((await self.session.execute(matches_q)).scalars().all())
        state["matches"] = [
            {
                "id": m.id,
                "round": m.round,
                "status": m.status.value if m.status else None,
                "team1_id": m.team1_id,
                "team2_id": m.team2_id,
                "winner_id": m.winner_id,
                "score_team1": m.score_team1,
                "score_team2": m.score_team2,
            }
            for m in matches
        ]

        # Standings
        standings_q = (
            select(Standings)
            .where(
                Standings.organization_id == organization_id,
                Standings.tournament_id == tournament_id,
            )
            .order_by(Standings.rank.asc().nullslast())
        )
        standings_rows = list((await self.session.execute(standings_q)).scalars().all())
        state["standings"] = [
            {
                "team_id": s.team_id,
                "rank": s.rank,
                "wins": s.wins,
                "losses": s.losses,
                "points": s.points,
            }
            for s in standings_rows
        ]

        return state
