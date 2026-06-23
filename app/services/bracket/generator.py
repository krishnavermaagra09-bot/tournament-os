"""
Bracket generator — supports ALL tournament formats.

Formats:
  single_elimination, double_elimination, triple_elimination
  round_robin, swiss, group_stage, group_stage_playoffs
  season_league, points_league, battle_royale, free_for_all
"""
import math
import logging
import random
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.bracket import Bracket
from app.database.models.team import Team
from app.database.models.tournament import TournamentFormat
from app.database.repositories.team import TeamRepository
from app.services.match.scheduler import MatchScheduler

logger = logging.getLogger(__name__)


def _seeded_pairings(teams: list[Team]) -> list[tuple[str | None, str | None]]:
    """Standard seed-based bracket pairing: 1v8, 2v7, etc. with byes."""
    n = len(teams)
    size = 1
    while size < n:
        size *= 2
    padded = teams + [None] * (size - n)
    pairings = []
    for i in range(size // 2):
        t1 = padded[i]
        t2 = padded[size - 1 - i]
        pairings.append((t1.id if t1 else None, t2.id if t2 else None))
    return pairings


def _round_robin_schedule(teams: list[Team]) -> list[list[tuple[str, str | None]]]:
    """
    Generate round-robin schedule using the circle method.
    Returns list of rounds, each round is a list of (team1_id, team2_id) tuples.
    """
    ids = [t.id for t in teams]
    if len(ids) % 2:
        ids.append(None)  # bye
    n = len(ids)
    rounds = []
    for _ in range(n - 1):
        round_pairings = []
        for i in range(n // 2):
            t1 = ids[i]
            t2 = ids[n - 1 - i]
            if t1 and t2:
                round_pairings.append((t1, t2))
        rounds.append(round_pairings)
        ids = [ids[0]] + [ids[-1]] + ids[1:-1]
    return rounds


def _split_into_groups(teams: list[Team], group_size: int) -> list[list[Team]]:
    """Split teams into balanced groups of approximately group_size."""
    num_groups = max(2, math.ceil(len(teams) / group_size))
    groups: list[list[Team]] = [[] for _ in range(num_groups)]
    for i, team in enumerate(teams):
        groups[i % num_groups].append(team)
    return [g for g in groups if g]


class BracketGenerator:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.scheduler = MatchScheduler(session)
        self.team_repo = TeamRepository(session)

    async def generate(
        self,
        organization_id: str,
        tournament_id: str,
        format: TournamentFormat,
        seeding_method: str = "seed",
        stage: int = 1,
        settings: dict | None = None,
    ) -> Bracket:
        teams = await self.team_repo.list_checked_in(organization_id, tournament_id)
        if not teams:
            raise ValueError("No checked-in teams to generate bracket for")

        if seeding_method == "random":
            random.shuffle(teams)
        else:
            teams.sort(key=lambda t: (t.seed or 9999))

        bracket = Bracket(
            organization_id=organization_id,
            tournament_id=tournament_id,
            bracket_type=format.value,
            stage=stage,
            name=f"Stage {stage} Bracket",
            settings=settings or {},
        )
        self.session.add(bracket)
        await self.session.flush()
        await self.session.refresh(bracket)

        if format in (
            TournamentFormat.SINGLE_ELIMINATION,
            TournamentFormat.DOUBLE_ELIMINATION,
            TournamentFormat.TRIPLE_ELIMINATION,
        ):
            await self._gen_elimination(bracket, teams, format)

        elif format == TournamentFormat.ROUND_ROBIN:
            await self._gen_round_robin(bracket, teams)

        elif format == TournamentFormat.SWISS:
            await self._gen_swiss_round1(bracket, teams)

        elif format == TournamentFormat.BATTLE_ROYALE:
            await self._gen_battle_royale(bracket, teams)

        elif format in (TournamentFormat.GROUP_STAGE, TournamentFormat.FREE_FOR_ALL):
            await self._gen_group_stage(bracket, teams, settings or {})

        elif format == TournamentFormat.GROUP_STAGE_PLAYOFFS:
            await self._gen_group_stage_playoffs(bracket, teams, settings or {})

        elif format in (TournamentFormat.SEASON_LEAGUE, TournamentFormat.POINTS_LEAGUE):
            await self._gen_league(bracket, teams, format)

        else:
            logger.warning("No specific generator for format %s — creating empty bracket", format)

        bracket.bracket_data = {
            "format": format.value,
            "team_count": len(teams),
            "seeding_method": seeding_method,
        }
        await self.session.flush()
        return bracket

    # ── Elimination ───────────────────────────────────────────────────────────

    async def _gen_elimination(
        self, bracket: Bracket, teams: list[Team], format: TournamentFormat
    ) -> None:
        pairings = _seeded_pairings(teams)
        await self.scheduler.schedule_round(
            bracket.organization_id, bracket.tournament_id, bracket.id,
            round=1, pairings=pairings
        )

    # ── Round Robin ───────────────────────────────────────────────────────────

    async def _gen_round_robin(self, bracket: Bracket, teams: list[Team]) -> None:
        rounds = _round_robin_schedule(teams)
        for i, round_pairings in enumerate(rounds, start=1):
            await self.scheduler.schedule_round(
                bracket.organization_id, bracket.tournament_id, bracket.id,
                round=i, pairings=round_pairings
            )

    # ── Swiss ─────────────────────────────────────────────────────────────────

    async def _gen_swiss_round1(self, bracket: Bracket, teams: list[Team]) -> None:
        """Swiss round 1 = random pairing; subsequent rounds use standings."""
        random.shuffle(teams)
        pairings = [(teams[i].id, teams[i + 1].id if i + 1 < len(teams) else None)
                    for i in range(0, len(teams), 2)]
        await self.scheduler.schedule_round(
            bracket.organization_id, bracket.tournament_id, bracket.id,
            round=1, pairings=pairings
        )

    # ── Group Stage ───────────────────────────────────────────────────────────

    async def _gen_group_stage(
        self, bracket: Bracket, teams: list[Team], settings: dict
    ) -> None:
        """
        Split teams into groups and run round-robin within each group.
        Stores group assignments in bracket.bracket_data["groups"].
        """
        group_size = settings.get("group_size", 4)
        groups = _split_into_groups(teams, group_size)

        group_data = {}
        round_offset = 0
        for g_idx, group_teams in enumerate(groups):
            group_label = f"Group {chr(65 + g_idx)}"  # A, B, C ...
            group_data[group_label] = [t.id for t in group_teams]
            rounds = _round_robin_schedule(group_teams)
            for r_idx, round_pairings in enumerate(rounds, start=1):
                # Encode group into match_number via offset so rounds don't collide
                tagged = [(t1, t2) for t1, t2 in round_pairings]
                await self.scheduler.schedule_round(
                    bracket.organization_id, bracket.tournament_id, bracket.id,
                    round=r_idx + round_offset, pairings=tagged,
                )
            round_offset += len(rounds)

        bracket.bracket_data = {
            "format": bracket.bracket_type,
            "team_count": len(teams),
            "groups": group_data,
            "group_size": group_size,
        }

    # ── Group Stage + Playoffs ────────────────────────────────────────────────

    async def _gen_group_stage_playoffs(
        self, bracket: Bracket, teams: list[Team], settings: dict
    ) -> None:
        """
        Phase 1: Group Stage — round-robin within groups.
        Phase 2: Playoffs — top N from each group advance to SE playoff bracket.

        The playoff bracket (stage 2) is auto-generated by the autonomous engine
        once all group matches complete. The bracket_data records the playoff
        advancement rule so the engine knows what to create.
        """
        group_size = settings.get("group_size", 4)
        advance_per_group = settings.get("advance_per_group", 2)
        groups = _split_into_groups(teams, group_size)

        group_data = {}
        round_offset = 0
        for g_idx, group_teams in enumerate(groups):
            group_label = f"Group {chr(65 + g_idx)}"
            group_data[group_label] = [t.id for t in group_teams]
            rounds = _round_robin_schedule(group_teams)
            for r_idx, round_pairings in enumerate(rounds, start=1):
                await self.scheduler.schedule_round(
                    bracket.organization_id, bracket.tournament_id, bracket.id,
                    round=r_idx + round_offset, pairings=round_pairings,
                )
            round_offset += len(rounds)

        total_advancers = len(groups) * advance_per_group
        bracket.bracket_data = {
            "format": bracket.bracket_type,
            "team_count": len(teams),
            "groups": group_data,
            "group_size": group_size,
            "advance_per_group": advance_per_group,
            "total_advancers": total_advancers,
            "playoff_format": "single_elimination",
            "phase": "group_stage",
        }
        logger.info(
            "Group Stage + Playoffs: %d groups, %d advance each → %d in playoffs",
            len(groups), advance_per_group, total_advancers,
        )

    # ── League (Season / Points) ──────────────────────────────────────────────

    async def _gen_league(
        self, bracket: Bracket, teams: list[Team], format: TournamentFormat
    ) -> None:
        """
        Full round-robin season league.

        season_league:  Win=3pts, Draw=1pt, Loss=0pts (football-style).
        points_league:  Win=2pts, Draw=1pt, Loss=0pts (standard).

        All matchdays are scheduled upfront. The champion is determined by
        standings at end of the final matchday — no playoff bracket is generated.
        """
        scoring = (
            {"win": 3, "draw": 1, "loss": 0}
            if format == TournamentFormat.SEASON_LEAGUE
            else {"win": 2, "draw": 1, "loss": 0}
        )

        rounds = _round_robin_schedule(teams)
        for r_idx, round_pairings in enumerate(rounds, start=1):
            await self.scheduler.schedule_round(
                bracket.organization_id, bracket.tournament_id, bracket.id,
                round=r_idx, pairings=round_pairings,
            )

        bracket.bracket_data = {
            "format": format.value,
            "team_count": len(teams),
            "total_matchdays": len(rounds),
            "scoring": scoring,
            "champion_by_standings": True,
        }
        logger.info(
            "League (%s): %d teams, %d matchdays, scoring=%s",
            format.value, len(teams), len(rounds), scoring,
        )

    # ── Battle Royale ─────────────────────────────────────────────────────────

    async def _gen_battle_royale(self, bracket: Bracket, teams: list[Team]) -> None:
        """Create lobby assignments for Battle Royale — one match per lobby."""
        lobby_size = bracket.settings.get("lobby_size", 16)
        lobbies = math.ceil(len(teams) / lobby_size)
        for lobby in range(1, lobbies + 1):
            m = await self.scheduler.create_match(
                organization_id=bracket.organization_id,
                tournament_id=bracket.tournament_id,
                bracket_id=bracket.id,
                round=1,
                match_number=lobby,
                lobby_number=lobby,
            )
            start = (lobby - 1) * lobby_size
            lobby_teams = teams[start:start + lobby_size]
            m.settings = {"lobby_teams": [t.id for t in lobby_teams]}
        await self.session.flush()
