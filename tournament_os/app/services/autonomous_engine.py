"""
Autonomous Tournament Engine — 2.0 feature.

When autonomous_mode=True on a tournament, this engine handles the full lifecycle
without organizer involvement:

  1. Monitors active rounds — advances winners when all matches are decided
  2. Generates next round automatically (Swiss / elimination)
  3. Creates Discord match channels for each new match
  4. DMs team captains with match details
  5. Updates standings after each result
  6. Completes + archives tournament when all rounds are done

This runs as a background task alongside the scheduler.
Interval: 30 seconds (more aggressive than the 60s status scheduler).
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def _run_once() -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.tournament import Tournament, TournamentStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        q = (
            select(Tournament)
            .where(
                Tournament.status == TournamentStatus.LIVE,
                Tournament.autonomous_mode.is_(True),
                Tournament.deleted_at.is_(None),
            )
        )
        tournaments = (await session.execute(q)).scalars().all()

    for t in tournaments:
        try:
            await _process_tournament(t.id, t.organization_id)
        except Exception as exc:
            logger.error(
                "Autonomous engine error for tournament %s: %s",
                t.id[:8], exc, exc_info=True,
            )


async def _process_tournament(tournament_id: str, organization_id: str) -> None:
    from app.database.session import AsyncSessionLocal
    from app.database.models.tournament import Tournament, TournamentStatus, TournamentFormat
    from app.database.models.match import Match, MatchStatus
    from app.database.models.bracket import Bracket
    from app.database.repositories.match import MatchRepository
    from app.database.repositories.tournament import TournamentRepository
    from app.services.bracket.advancement import BracketAdvancementService
    from sqlalchemy import select, and_

    async with AsyncSessionLocal() as session:
        t = await session.get(Tournament, tournament_id)
        if not t or t.status != TournamentStatus.LIVE:
            return

        # Get the active bracket
        bracket_q = select(Bracket).where(
            Bracket.tournament_id == tournament_id,
            Bracket.organization_id == organization_id,
        ).order_by(Bracket.stage.desc())
        bracket = (await session.execute(bracket_q)).scalars().first()
        if not bracket:
            return

        match_repo = MatchRepository(session)
        all_matches = await match_repo.list_all(organization_id, tournament_id)

        if not all_matches:
            return

        pending = [m for m in all_matches if m.status not in (MatchStatus.COMPLETED, MatchStatus.ARCHIVED, MatchStatus.VOIDED)]
        completed = [m for m in all_matches if m.status == MatchStatus.COMPLETED]

        # Swiss: generate next round when current round is fully complete
        if t.format.value == "swiss":
            await _handle_swiss_auto(session, t, bracket, all_matches, pending)
            return

        # Group Stage + Playoffs: transition from groups to playoff bracket
        if t.format.value == "group_stage_playoffs":
            await _handle_group_stage_playoffs_auto(session, t, bracket, all_matches, pending, organization_id)
            return

        # League (season/points): check if all matchdays are done → complete
        if t.format.value in ("season_league", "points_league"):
            await _handle_league_auto(session, t, bracket, all_matches, pending, organization_id)
            return

        # Elimination: advance winners and generate next round
        if t.format.value in ("single_elimination", "double_elimination", "triple_elimination"):
            if not pending:
                # All matches complete — tournament is done
                await _auto_complete_tournament(session, t, organization_id)
                return

        # No more work if there are still pending matches in the current round
        current_round = max((m.round for m in pending if m.round is not None), default=0)
        current_round_pending = [m for m in pending if m.round == current_round]
        if current_round_pending:
            return  # Still waiting for current round to finish

        # All current round matches done — generate next round
        last_round = max((m.round for m in all_matches if m.round is not None), default=0)
        if last_round == 0:
            return

        last_round_matches = [m for m in all_matches if m.round == last_round]
        all_last_done = all(m.status == MatchStatus.COMPLETED for m in last_round_matches)
        if not all_last_done:
            return

        logger.info(
            "Autonomous: tournament %s round %s complete — generating round %s",
            tournament_id[:8], last_round, last_round + 1,
        )

        async with AsyncSessionLocal() as adv_session:
            async with adv_session.begin():
                adv = BracketAdvancementService(adv_session)
                try:
                    new_matches = await adv.generate_next_round(organization_id, tournament_id, bracket.id)
                    if new_matches:
                        # Create Discord match channels for the new round
                        asyncio.create_task(
                            _create_match_channels(
                                organization_id, tournament_id, [m.id for m in new_matches]
                            )
                        )
                except ValueError as exc:
                    if "complete" in str(exc).lower() or "no teams" in str(exc).lower():
                        await _auto_complete_tournament(adv_session, t, organization_id)
                    else:
                        logger.warning("Next round generation failed for %s: %s", tournament_id[:8], exc)


async def _handle_swiss_auto(session, tournament, bracket, all_matches, pending) -> None:
    """Swiss: pair next round by current standings when all matches in current round finish."""
    from app.database.models.match import MatchStatus
    from app.services.bracket.advancement import BracketAdvancementService

    current_round = max((m.round for m in all_matches if m.round is not None), default=0)
    round_matches = [m for m in all_matches if m.round == current_round]
    if any(m.status not in (MatchStatus.COMPLETED, MatchStatus.ARCHIVED, MatchStatus.VOIDED) for m in round_matches):
        return  # Current round not done

    total_rounds = bracket.settings.get("total_rounds", 0) if bracket.settings else 0
    if total_rounds and current_round >= total_rounds:
        async with session.begin():
            t_row = await session.get(type(tournament), tournament.id)
            if t_row:
                from app.database.models.tournament import TournamentStatus
                t_row.status = TournamentStatus.COMPLETED
                logger.info("Autonomous Swiss: tournament %s completed after %s rounds", tournament.id[:8], current_round)
        return

    logger.info("Autonomous Swiss: generating round %s for tournament %s", current_round + 1, tournament.id[:8])
    from app.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as adv_session:
        async with adv_session.begin():
            adv = BracketAdvancementService(adv_session)
            try:
                new_matches = await adv.generate_swiss_round(
                    tournament.organization_id, tournament.id, bracket.id, current_round + 1
                )
                if new_matches:
                    asyncio.create_task(
                        _create_match_channels(
                            tournament.organization_id, tournament.id, [m.id for m in new_matches]
                        )
                    )
            except Exception as exc:
                logger.warning("Swiss round generation failed: %s", exc)


async def _handle_group_stage_playoffs_auto(
    session, tournament, bracket, all_matches, pending, organization_id: str
) -> None:
    """
    Group Stage + Playoffs automation:
    - Phase 1 (group_stage): wait for all group matches to complete, then
      determine top N teams per group and generate a SE playoff bracket.
    - Phase 2 (playoffs): run like single_elimination until winner found.
    """
    from app.database.models.match import MatchStatus
    from app.database.models.standings import Standings
    from app.database.session import AsyncSessionLocal
    from sqlalchemy import select

    bd = bracket.bracket_data or {}
    phase = bd.get("phase", "group_stage")

    if phase == "group_stage":
        if pending:
            return  # Group matches still running

        # All group matches done — determine advancers
        advance_per_group = bd.get("advance_per_group", 2)
        groups: dict = bd.get("groups", {})

        async with AsyncSessionLocal() as s:
            async with s.begin():
                standings_q = (
                    select(Standings)
                    .where(
                        Standings.organization_id == organization_id,
                        Standings.tournament_id == tournament.id,
                    )
                    .order_by(Standings.wins.desc(), Standings.points.desc())
                )
                all_standings = list((await s.execute(standings_q)).scalars().all())
                standings_map = {st.team_id: st for st in all_standings}

                playoff_team_ids: list[str] = []
                for group_label, team_ids in groups.items():
                    group_standings = sorted(
                        [standings_map[tid] for tid in team_ids if tid in standings_map],
                        key=lambda x: (-x.wins, -x.points),
                    )
                    playoff_team_ids.extend(
                        [gs.team_id for gs in group_standings[:advance_per_group]]
                    )

                logger.info(
                    "GSP auto: %d teams advance to playoffs for tournament %s",
                    len(playoff_team_ids), tournament.id[:8],
                )

                # Generate playoff bracket (stage 2 = SE)
                from app.services.bracket.generator import BracketGenerator
                from app.database.models.tournament import TournamentFormat
                from app.database.repositories.team import TeamRepository
                from app.database.models.team import Team

                team_q = select(Team).where(Team.id.in_(playoff_team_ids))
                playoff_teams = list((await s.execute(team_q)).scalars().all())

                playoff_bracket = await BracketGenerator(s).generate(
                    organization_id=organization_id,
                    tournament_id=tournament.id,
                    format=TournamentFormat.SINGLE_ELIMINATION,
                    stage=2,
                )
                # Update original bracket phase
                bracket_obj = await s.get(type(bracket), bracket.id)
                if bracket_obj:
                    new_bd = dict(bracket_obj.bracket_data or {})
                    new_bd["phase"] = "playoffs"
                    bracket_obj.bracket_data = new_bd

        logger.info("GSP auto: playoff bracket generated for tournament %s", tournament.id[:8])

    elif phase == "playoffs":
        # Behave like single elimination
        if not pending:
            await _auto_complete_tournament(session, tournament, organization_id)


async def _handle_league_auto(
    session, tournament, bracket, all_matches, pending, organization_id: str
) -> None:
    """
    League automation (season_league / points_league):
    All matchdays are scheduled upfront. When all are complete, the
    tournament is auto-completed — champion determined by standings.
    """
    if not pending:
        logger.info(
            "Autonomous League: all matchdays complete for tournament %s — completing",
            tournament.id[:8],
        )
        await _auto_complete_tournament(session, tournament, organization_id)


async def _create_match_channels(
    organization_id: str,
    tournament_id: str,
    match_ids: list[str],
) -> None:
    """
    For each new match, create a private Discord channel and notify team captains.
    Runs as a fire-and-forget background task.
    """
    from app.services.notification.discord_delivery import get_bot, notify_match_assigned
    bot = get_bot()
    if not bot:
        logger.debug("_create_match_channels: bot not registered yet, skipping channel creation")
        return

    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.match import Match
        from app.database.models.team import Team
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from app.database.models.user import User
        from app.services.match.channel_manager import MatchChannelManager
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            tournament = await session.get(Tournament, tournament_id)
            if not tournament:
                return

            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                return

            guild_settings: dict = guild.settings or {}
            channel_ids: dict = guild_settings.get("channel_ids", {})
            tc: dict = tournament.channel_config or {}

            guild_id_str = guild.discord_guild_id
            category_id = tc.get("tournament_category_id") or tc.get("category_id")
            staff_role_ids = guild_settings.get("staff_role_ids", {})
            announcements_channel_id = (
                channel_ids.get("announcements") or tc.get("announcements_channel_id")
            )
            schedule_channel_id = (
                channel_ids.get("schedule") or tc.get("schedule_channel_id")
            )

            channel_mgr = MatchChannelManager(session)

            for match_id in match_ids:
                match = await session.get(Match, match_id)
                if not match or not match.team1_id or not match.team2_id:
                    continue

                team1 = await session.get(Team, match.team1_id)
                team2 = await session.get(Team, match.team2_id)
                if not team1 or not team2:
                    continue

                team1_name = team1.name
                team2_name = team2.name

                # Create match channel
                try:
                    ch_id = await channel_mgr.create_match_channel(
                        bot=bot,
                        match=match,
                        team1_name=team1_name,
                        team2_name=team2_name,
                        guild_id_str=guild_id_str,
                        tournament_category_id=category_id,
                        staff_role_ids=staff_role_ids,
                    )
                    if ch_id:
                        # Persist channel ID on the match
                        match.private_channel_id = str(ch_id)
                        await session.flush()
                        # Post match info embed
                        await channel_mgr.post_match_info(
                            bot=bot,
                            channel_id=ch_id,
                            match=match,
                            team1_name=team1_name,
                            team2_name=team2_name,
                        )
                except Exception as exc:
                    logger.warning("Failed to create match channel for match %s: %s", match_id[:8], exc)

                # Find team captains' Discord IDs
                async def _get_captain_discord_id(team: Team) -> str | None:
                    if not team.captain_id:
                        return None
                    user = await session.get(User, team.captain_id)
                    return user.discord_user_id if user else None

                cap1_id = await _get_captain_discord_id(team1)
                cap2_id = await _get_captain_discord_id(team2)

                # Notify via Discord
                channel_id = int(match.private_channel_id) if match.private_channel_id else None
                await notify_match_assigned(
                    match_id_short=match.id[:8],
                    round_num=match.round or 0,
                    match_num=match.match_number or 0,
                    tournament_name=tournament.name,
                    team1_name=team1_name,
                    team2_name=team2_name,
                    match_channel_id=channel_id,
                    captain1_discord_id=cap1_id,
                    captain2_discord_id=cap2_id,
                )

            await session.commit()

        # Announce new round to schedule channel
        if match_ids and schedule_channel_id:
            from app.services.notification.discord_delivery import notify_round_started
            from app.database.models.match import Match as MatchModel
            first_round_num: int | None = None
            async with AsyncSessionLocal() as s2:
                first_match = await s2.get(MatchModel, match_ids[0])
                if first_match:
                    first_round_num = first_match.round
            if first_round_num is not None:
                await notify_round_started(
                    tournament_name=tournament.name,
                    round_num=first_round_num,
                    match_count=len(match_ids),
                    schedule_channel_id=schedule_channel_id,
                )

    except Exception as exc:
        logger.error(
            "_create_match_channels failed for tournament %s: %s",
            tournament_id[:8], exc, exc_info=True,
        )


async def _auto_complete_tournament(session, tournament, organization_id: str) -> None:
    """Transition tournament to COMPLETED, take snapshot, post results, then schedule archive."""
    from app.database.models.tournament import TournamentStatus
    from app.services.tournament.lifecycle import TournamentLifecycleService
    from app.database.repositories.tournament import TournamentRepository

    try:
        async with session.begin():
            repo = TournamentRepository(session)
            t = await repo.get_by_id(tournament.id, organization_id)
            if t and t.can_transition_to(TournamentStatus.COMPLETED):
                svc = TournamentLifecycleService(session)
                await svc.transition_status(
                    tournament_id=tournament.id,
                    organization_id=organization_id,
                    new_status=TournamentStatus.COMPLETED,
                    actor_id="autonomous_engine",
                    actor_type="system",
                )
                logger.info("Autonomous engine: tournament %s auto-completed", tournament.id[:8])

                # Auto-snapshot on completion
                try:
                    from app.services.snapshot.snapshot_service import SnapshotService
                    snap_svc = SnapshotService(session)
                    await snap_svc.take(
                        tournament_id=tournament.id,
                        organization_id=organization_id,
                        trigger="tournament_completed",
                        label="Final state at tournament completion",
                    )
                except Exception as snap_exc:
                    logger.warning("Auto-snapshot on completion failed: %s", snap_exc)

        # Fire completion notification
        asyncio.create_task(_notify_tournament_completed(tournament.id, organization_id))

        # Schedule auto-archive (lock channels, set ARCHIVED status after 10 minutes)
        asyncio.create_task(_auto_archive_tournament(tournament.id, organization_id, delay_seconds=600))

    except Exception as exc:
        logger.error("Auto-complete failed for tournament %s: %s", tournament.id[:8], exc)


async def _auto_archive_tournament(tournament_id: str, organization_id: str, delay_seconds: int = 600) -> None:
    """After a delay, transition COMPLETED → ARCHIVED and lock Discord channels."""
    await asyncio.sleep(delay_seconds)
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament, TournamentStatus
        from app.database.repositories.tournament import TournamentRepository

        async with AsyncSessionLocal() as session:
            repo = TournamentRepository(session)
            t = await repo.get_by_id(tournament_id, organization_id)
            if not t or t.status != TournamentStatus.COMPLETED:
                return

            if not t.can_transition_to(TournamentStatus.ARCHIVED):
                logger.debug("Cannot archive tournament %s from status %s", tournament_id[:8], t.status.value)
                return

            async with session.begin():
                from app.services.tournament.lifecycle import TournamentLifecycleService
                svc = TournamentLifecycleService(session)
                await svc.transition_status(
                    tournament_id=tournament_id,
                    organization_id=organization_id,
                    new_status=TournamentStatus.ARCHIVED,
                    actor_id="autonomous_engine",
                    actor_type="system",
                )
                logger.info("Autonomous engine: tournament %s auto-archived", tournament_id[:8])

        # Lock Discord channels (make them read-only)
        asyncio.create_task(_lock_tournament_channels(tournament_id, organization_id))

    except Exception as exc:
        logger.warning("Auto-archive failed for tournament %s: %s", tournament_id[:8], exc)


async def _lock_tournament_channels(tournament_id: str, organization_id: str) -> None:
    """Make all channels in the tournament category read-only after archiving."""
    try:
        from app.services.notification.discord_delivery import get_bot
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from sqlalchemy import select

        bot = get_bot()
        if not bot:
            return

        async with AsyncSessionLocal() as session:
            tournament = await session.get(Tournament, tournament_id)
            if not tournament:
                return
            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild_row = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild_row:
                return

            tc: dict = tournament.channel_config or {}
            category_id = tc.get("tournament_category_id") or tc.get("category_id")
            if not category_id:
                return

        discord_guild = bot.get_guild(int(guild_row.discord_guild_id))
        if not discord_guild:
            return

        cat = discord_guild.get_channel(int(category_id))
        if not cat or not hasattr(cat, "channels"):
            return

        overwrite = discord.PermissionOverwrite(send_messages=False, add_reactions=False)
        for ch in cat.channels:
            try:
                await ch.set_permissions(discord_guild.default_role, overwrite=overwrite)
            except Exception:
                pass

        logger.info("Locked %d channels in tournament %s category", len(cat.channels), tournament_id[:8])

    except Exception as exc:
        logger.warning("_lock_tournament_channels failed for %s: %s", tournament_id[:8], exc)


async def _notify_tournament_completed(tournament_id: str, organization_id: str) -> None:
    """Post final standings to the announcements channel."""
    try:
        from app.database.session import AsyncSessionLocal
        from app.database.models.tournament import Tournament
        from app.database.models.guild import Guild
        from app.database.models.standings import Standings
        from app.database.models.team import Team
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            tournament = await session.get(Tournament, tournament_id)
            if not tournament:
                return

            guild_q = select(Guild).where(
                Guild.organization_id == organization_id,
                Guild.deleted_at.is_(None),
            ).limit(1)
            guild = (await session.execute(guild_q)).scalar_one_or_none()
            if not guild:
                return

            guild_settings: dict = guild.settings or {}
            channel_ids: dict = guild_settings.get("channel_ids", {})
            tc: dict = tournament.channel_config or {}
            announcements_ch = channel_ids.get("announcements") or tc.get("announcements_channel_id")

            # Get top 3 standings
            standings_q = (
                select(Standings)
                .where(
                    Standings.organization_id == organization_id,
                    Standings.tournament_id == tournament_id,
                )
                .order_by(Standings.rank.asc().nulls_last(), Standings.wins.desc())
                .limit(3)
            )
            top_standings = (await session.execute(standings_q)).scalars().all()

            winner_name: str | None = None
            summary_lines: list[str] = []
            medals = ["🥇", "🥈", "🥉"]

            for i, s in enumerate(top_standings):
                team = await session.get(Team, s.team_id)
                team_name = team.name if team else "Unknown"
                if i == 0:
                    winner_name = team_name
                summary_lines.append(
                    f"{medals[i]} **{team_name}** — {s.wins}W / {s.losses}L"
                )

        standings_summary = "\n".join(summary_lines) if summary_lines else None

        from app.services.notification.discord_delivery import notify_tournament_completed
        await notify_tournament_completed(
            tournament_name=tournament.name,
            winner_team_name=winner_name,
            announcements_channel_id=announcements_ch,
            standings_summary=standings_summary,
        )

    except Exception as exc:
        logger.error("_notify_tournament_completed failed for %s: %s", tournament_id[:8], exc)


async def run_autonomous_engine() -> None:
    """Loop: process all autonomous tournaments every 30 seconds."""
    logger.info("Autonomous tournament engine started (30-second interval)")
    while True:
        try:
            await _run_once()
        except Exception as exc:
            logger.error("Autonomous engine loop error: %s", exc, exc_info=True)
        await asyncio.sleep(30)
